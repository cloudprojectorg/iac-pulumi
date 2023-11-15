import pulumi
from pulumi_aws import ec2, get_availability_zones, rds, route53, iam
from pulumi import Config
import ipaddress
from pulumi import export
import json
import pulumi_aws as aws
import base64

# Create a Config instance
config = Config()

# Resource Tag
common_tag = {"Name": "my-pulumi-infra"}

# Fetch configurations
vpc_name = config.require("my_vpc_name")
vpc_cidr = config.require("my_vpc_cidr")
vpc_internet_gateway = config.require("my_internet_gateway")
mailgun_domain = config.require("mailgun_domain")
mailgun_sender = config.require("mailgun_sender")
ses_region = config.require("ses_region")
ses_sender = config.require("ses_sender")
api_key = config.require_secret('api_key')
public_subnets_cidr = config.require_object("public_subnets_cidr")
private_subnets_cidr = config.require_object("private_subnets_cidr")

# Create a VPC
vpc = ec2.Vpc(vpc_name, cidr_block=vpc_cidr,
              enable_dns_support=True,
              enable_dns_hostnames=True,
              tags={**common_tag, "Type": "VPC"})

# Create an Internet Gateway
ig = ec2.InternetGateway("internetGateway", vpc_id=vpc.id,
                         tags={**common_tag, "Type": "Internet Gateway"})

# Get available AZs
azs = get_availability_zones().names
# Use a maximum of 3 AZs
num_azs = min(len(azs), 3)  

# Create Public Subnets
public_subnets = []
for i, cidr in enumerate(public_subnets_cidr[:num_azs]):
    subnet = ec2.Subnet(f"publicSubnet-{i+1}",
                        vpc_id=vpc.id,
                        cidr_block=cidr,
                        availability_zone=azs[i],
                        map_public_ip_on_launch=True,
                        tags={**common_tag, "Type": f"publicSubnet-{i+1}"})
    public_subnets.append(subnet)

# Create Private Subnets
private_subnets = []
for i, cidr in enumerate(private_subnets_cidr[:num_azs]):
    subnet = ec2.Subnet(f"privateSubnet-{i+4}",
                        vpc_id=vpc.id,
                        cidr_block=cidr,
                        availability_zone=azs[i],
                        tags={**common_tag, "Type": f"privateSubnet-{i+4}"})
    private_subnets.append(subnet)

# Create Public Route Table
public_route_table = ec2.RouteTable("publicRouteTable", vpc_id=vpc.id, tags={
                                    **common_tag, "Type": "publicRouteTable"})
public_route = ec2.Route("publicRoute", route_table_id=public_route_table.id,
                         destination_cidr_block="0.0.0.0/0", gateway_id=ig.id)

# Associate Public Subnets to Public Route Table
for i, subnet in enumerate(public_subnets):
    ec2.RouteTableAssociation(
        f"publicRta-{i}", route_table_id=public_route_table.id, subnet_id=subnet.id)

# Create Private Route Table
private_route_table = ec2.RouteTable("privateRouteTable", vpc_id=vpc.id, tags={
                                     **common_tag, "Type": "privateRouteTable"})

# Associate Private Subnets to Private Route Table
for i, subnet in enumerate(private_subnets):
    ec2.RouteTableAssociation(
        f"privateRta-{i}", route_table_id=private_route_table.id, subnet_id=subnet.id)
    
# Load balancer Security Group
load_balancer_sg = ec2.SecurityGroup('loadBalancerSecurityGroup',
                                     vpc_id=vpc.id,
                                     description='Security group for load balancer',
                                     ingress=[
                                         ec2.SecurityGroupIngressArgs(
                                             protocol='tcp', 
                                             from_port=80, 
                                             to_port=80, 
                                             cidr_blocks=["0.0.0.0/0"]),
                                         ec2.SecurityGroupIngressArgs(
                                             protocol='tcp', 
                                             from_port=443, 
                                             to_port=443, 
                                             cidr_blocks=["0.0.0.0/0"]),
                                     ],
                                     egress=[
                                         ec2.SecurityGroupEgressArgs(
                                             protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"]),
                                     ],
                                     tags={**common_tag,
                                           "Type": "loadBalancerSecurityGroup"}
                                     )


# Application Security Group
application_sg = ec2.SecurityGroup("applicationSecurityGroup",
                                   vpc_id=vpc.id,
                                   description="Security group for application server",
                                   ingress=[
                                       ec2.SecurityGroupIngressArgs(
                                           protocol="tcp",
                                           from_port=22,
                                           to_port=22,
                                           cidr_blocks=["0.0.0.0/0"]),
                                       {
                                           "protocol": "tcp",
                                           "from_port": 8080,
                                           "to_port": 8080,
                                           "security_groups": [load_balancer_sg.id]
                                       }
                                   ],
                                   egress=[
                                        ec2.SecurityGroupEgressArgs(
                                            protocol="tcp", from_port=3306, to_port=3306, cidr_blocks=["0.0.0.0/0"]),
                                        ec2.SecurityGroupEgressArgs(
                                            protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"]),
                                        ],
                                   tags={**common_tag,
                                         "Type": "applicationSecurityGroup"}
                                   )

# Database Security Group
db_security_group = ec2.SecurityGroup("databaseSecurityGroup",
                                      vpc_id=vpc.id,
                                      description="Security group for RDS instances",
                                      egress=[
                                        ec2.SecurityGroupEgressArgs(
                                            protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"]),
                                        ],
                                      ingress=[
                                        ec2.SecurityGroupIngressArgs(
                                            protocol="tcp",
                                            from_port=3306,  # For MySQL/MariaDB
                                            to_port=3306,
                                            security_groups=[application_sg.id]
                                          )
                                      ],
                                      tags={**common_tag, "Type": "databaseSecurityGroup"})

# RDS Subnet Group
rds_subnet_group = rds.SubnetGroup("db-subnet-group",
                                   subnet_ids=[
                                       subnet.id for subnet in private_subnets],
                                   description="RDS subnet group using private subnets",
                                   tags={**common_tag, "Type": "RDSSubnetGroup"}
                                   )

# RDS Parameter Group
db_parameter_group = rds.ParameterGroup("custom-db-parameter-group",
                                        family="mysql8.0",  
                                        description="Custom parameter group for RDS",
                                        parameters=[
                                            {
                                                "name": "character_set_server",
                                                "value": "utf8"
                                            },
                                            {
                                                "name": "character_set_client",
                                                "value": "utf8"
                                            }
                                        ],
                                        tags={**common_tag, "Type": "customDbParameterGroup"},
                                        opts=pulumi.ResourceOptions(delete_before_replace=True))

# RDS Instance
rds_instance = rds.Instance("csye6225",
                            engine="mysql", 
                            instance_class="db.t2.micro",
                            allocated_storage=25,
                            storage_type="gp2",
                            db_name="csye6225",
                            username="csye6225",
                            identifier="csye6225",                    
                            password=config.require_secret("database_password"),
                            parameter_group_name=db_parameter_group.name,
                            skip_final_snapshot=True,
                            vpc_security_group_ids=[db_security_group.id],
                            db_subnet_group_name=rds_subnet_group.name,
                            multi_az=False,
                            publicly_accessible=False,
                            apply_immediately=True,
                            tags={**common_tag, "Type": "RDSInstance"})

# Load Balancer (ELB)
load_balancer = aws.lb.LoadBalancer("app-load-balancer",
                                    name="demoLoadBalancer",
                                    internal=False,
                                    load_balancer_type="application",
                                    security_groups=[load_balancer_sg.id],
                                    subnets=[
                                        subnet.id for subnet in public_subnets],
                                    tags={'Name': "Load Balancer"},
                                    opts=pulumi.ResourceOptions(
                                        depends_on=([
                                            load_balancer_sg] + public_subnets)
                                    )
                                    )

# Target Group
target_group = aws.lb.TargetGroup("target-group",
                                  name_prefix="demoTG",
                                  port=8080,
                                  protocol="HTTP",
                                  vpc_id=vpc.id,
                                  # Other configurations like health checks
                                  target_type="instance",
                                  health_check=aws.lb.TargetGroupHealthCheckArgs(
                                      enabled=True,
                                      path="/healthz",
                                      port="8080",
                                      protocol="HTTP",
                                      healthy_threshold=3,
                                      unhealthy_threshold=5,
                                      timeout=5,
                                      interval=30,
                                      matcher="200"
                                  ),
                                  tags={"Name": "target-group"},
                                  opts=pulumi.ResourceOptions(depends_on=[vpc]
                                  )
                                  )

# Listener
listener = aws.lb.Listener("listener",
                           load_balancer_arn=load_balancer.arn,
                           port=80,
                           protocol="HTTP",
                           default_actions=[aws.lb.ListenerDefaultActionArgs(
                               type="forward",
                               target_group_arn=target_group.arn
                           )],
                           opts=pulumi.ResourceOptions(depends_on=[load_balancer, target_group]
                           )
                           )

# # User Data for EC2
# user_data = f"""#!/bin/bash
# export DB_HOST={rds_instance.endpoint}
# export DB_USER=csye6225
# export DB_PASSWORD={config.require_secret("db_password")}

# systemctl daemon-reload
# systemctl restart webapp
# """


# Split RDS endpoint to remove port number
end_point = rds_instance.endpoint.apply(lambda endpoint: endpoint.split(":")[0])
database_password = config.require_secret("database_password")

# Function to generate the user data script
def generate_user_data_script(hostname, password):
    # hostname = endpoint.split(":")[0]

    return f"""#!/bin/bash
    set -e
    echo "User data script started to execute" | sudo tee -a /var/log/cloud-init-output.log

    # # Reload systemd and restart the service
    # sudo systemctl daemon-reload
    # sudo systemctl restart webapp.service

    # Write environment variables in separate file
    echo "DB_HOST={hostname}" | sudo tee -a /etc/webapp.env
    echo "DB_USERNAME=csye6225" | sudo tee -a /etc/webapp.env
    echo "DB_PASSWORD={password}" | sudo tee -a /etc/webapp.env
    echo "DB_NAME=csye6225" | sudo tee -a /etc/webapp.env

    # Configuration for SES
    # echo "SES_REGION={ses_region}" | sudo tee -a /etc/webapp.env
    # echo "SES_SENDER_EMAIL={ses_sender}" | sudo tee -a /etc/webapp.env

    # Echo the environment variables to the log
    # cat /etc/webapp.env >> /var/log/userdata.log
    echo "DB_HOST=${hostname}" | sudo tee -a /var/log/userdata.log
    echo "DB_USERNAME=csye6225" | sudo tee -a /var/log/userdata.log
    echo "DB_NAME=csye6225" | sudo tee -a /var/log/userdata.log

    # echo "MAILGUN_DOMAIN=${mailgun_domain}" | sudo tee -a /var/log/userdata.log
    # echo "MAILGUN_SENDER=${mailgun_sender}" | sudo tee -a /var/log/userdata.log
    # echo "SES_REGION=${ses_region}" | sudo tee -a /var/log/userdata.log
    # echo "SES_SENDER_EMAIL=${ses_sender}" | sudo tee -a /var/log/userdata.log

    # Write Cloudwatch agent configuration to file
    sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/webapp/cloudwatch-agent-config.json
    sudo mv /opt/webapp/cloudwatch-agent-config.json /opt/cloudwatch-config.json

    # Restart the Cloudwatch agent to apply configurations
    # sudo systemctl enable amazon-cloudwatch-agent
    # sudo systemctl restart amazon-cloudwatch-agent

    echo "User data script completed the execution" | sudo tee -a /var/log/cloud-init-output.log

    # Reload systemd 
    sudo systemctl daemon-reload

    # Introduce a delay before starting the service
    sleep 30
    sudo systemctl enable webapp.service
    sudo systemctl start webapp.service
    """

# Use the apply method to generate the user data script with the RDS endpoint and password
user_data_script = pulumi.Output.all(end_point, database_password).apply(
    lambda args: generate_user_data_script(*args))

# Encode user data for use in launch configuration
encoded_user_data_script = user_data_script.apply(
    lambda uds: base64.b64encode(uds.encode('utf-8')).decode('utf-8'))

#For EC2 : IAM Role
role_iam = iam.Role("ec2Role",
                assume_role_policy=json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Action": "sts:AssumeRole",
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "ec2.amazonaws.com"
                        }
                    }]
                }))

policy_ses = iam.Policy("sesPolicy",
                        description="Policy to allow EC2 to send emails through SES",
                        policy=json.dumps({
                            "Version": "2012-10-17",
                            "Statement": [{
                                "Effect": "Allow",
                                "Action": [
                                    "ses:SendEmail",
                                    "ses:SendRawEmail",
                                    "ses:SendTemplatedEmail"
                                ],
                                "Resource": "*"
                            }]
                        }))

# Attach custom SES policy with the role
policy_ses_attachment = iam.RolePolicyAttachment("sesPolicyAttachment",
                                                 role=role_iam.name,
                                                 policy_arn=policy_ses.arn)


# List policy ARNs you want to attach with the role
policies = [
    "arn:aws:iam::aws:policy/AmazonEC2FullAccess",
    "arn:aws:iam::aws:policy/AmazonRDSFullAccess",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    "arn:aws:iam::aws:policy/AmazonVPCFullAccess",
    "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
    "arn:aws:iam::aws:policy/AutoScalingFullAccess",
    "arn:aws:iam::aws:policy/ElasticLoadBalancingFullAccess",
    "arn:aws:iam::aws:policy/IAMUserChangePassword"
]

# Attach policies with the role
for policy_arn in policies:
    attachment = aws.iam.RolePolicyAttachment(f'attach-{policy_arn.split(":")[-1]}',
                                              policy_arn=policy_arn,
                                              role=role_iam.name)
    

# Create EC2 Instance Profile
profile_instance = iam.InstanceProfile("instanceProfile", role=role_iam.name)

# EC2 Instance
ami_id = config.require("ami_id")  

ami = ec2.get_ami(most_recent=True,
                  owners=["amazon"],
                  filters=[{"name":"name","values":["amzn2-ami-hvm-*-x86_64-gp2"]}])

ec2_launch_template = ec2.LaunchTemplate('launchTemplate',
                                        name_prefix="webapp-lt",
                                        image_id=ami_id,
                                        instance_type="t2.micro",
                                        key_name="keypair_webapp",
                                        network_interfaces=[{
                                            'associate_public_ip_address': True,
                                            'security_groups': [application_sg.id]
                                        }],
                                        block_device_mappings=[{
                                            'device_name': ami.root_device_name,
                                            'ebs': {
                                                'volume_size': 25,
                                                'volume_type': "gp2",
                                                'delete_on_termination': True
                                            }
                                        }],
                                        user_data=encoded_user_data_script,
                                        iam_instance_profile=aws.ec2.LaunchTemplateIamInstanceProfileArgs(
                                            arn=profile_instance.arn
                                        ),
                                        disable_api_termination=False,
                                        tag_specifications=[
                                            aws.ec2.LaunchTemplateTagSpecificationArgs(
                                                resource_type='instance',
                                                tags={**common_tag,
                                                    "Type": "webInstance"}
                                            )
                                        ],
                                        opts=pulumi.ResourceOptions(depends_on=[
                                            application_sg,
                                            profile_instance
                                        ]))

# Auto Scaling Group
auto_scaling_group = aws.autoscaling.Group('autoScalingGroup',
                                           launch_template=aws.autoscaling.GroupLaunchTemplateArgs(
                                               id=ec2_launch_template.id,
                                               version='$Latest'
                                           ),
                                           # List of subnet IDs
                                           vpc_zone_identifiers=[
                                               subnet.id for subnet in public_subnets],
                                           min_size=1,
                                           max_size=3,
                                           desired_capacity=1,
                                           target_group_arns=[
                                               target_group.arn],
                                           health_check_type='ELB',
                                           health_check_grace_period=60,
                                           force_delete=True,
                                           tags=[{
                                               'key': 'Name',
                                               'value': 'AutoScaleGroup',
                                               'propagate_at_launch': True,
                                           }],
                                           opts=pulumi.ResourceOptions(depends_on=[
                                               ec2_launch_template, target_group] + public_subnets)
                                           )

# Scale-Up Policy
scale_up_policy = aws.autoscaling.Policy("scaleUpPolicy",
                                         autoscaling_group_name=auto_scaling_group.name,
                                         adjustment_type="ChangeInCapacity",
                                         scaling_adjustment=1,
                                         cooldown=60
                                         )

# Scale-Down Policy
scale_down_policy = aws.autoscaling.Policy("scaleDownPolicy",
                                           autoscaling_group_name=auto_scaling_group.name,
                                           adjustment_type="ChangeInCapacity",
                                           scaling_adjustment=-1,
                                           cooldown=60
                                           )

# Scale-Up Cloud Watch alarm
scale_up_alarm = aws.cloudwatch.MetricAlarm("scaleUpAlarm",
                                            comparison_operator="GreaterThanThreshold",
                                            evaluation_periods=2,
                                            metric_name="CPUUtilization",
                                            namespace="AWS/EC2",
                                            period=120,
                                            statistic="Average",
                                            threshold=5,
                                            alarm_actions=[
                                                scale_up_policy.arn],
                                            dimensions={
                                                "AutoScalingGroupName": auto_scaling_group.name}
                                            )

# Scale-Down Cloud Watch alarm
scale_down_alarm = aws.cloudwatch.MetricAlarm("scaleDownAlarm",
                                              comparison_operator="LessThanThreshold",
                                              evaluation_periods=2,
                                              metric_name="CPUUtilization",
                                              namespace="AWS/EC2",
                                              period=120,
                                              statistic="Average",
                                              threshold=3,
                                              alarm_actions=[
                                                  scale_down_policy.arn],
                                              dimensions={
                                                  "AutoScalingGroupName": auto_scaling_group.name}
                                              )

# Access hosted zone ID and domain name from the configuration
hosted_zone_id = config.require("hosted_zone_id")
domain_name = config.require("domain_name")
# public_ip = ec2_instance.public_ip # Get the public IP of the EC2 instance   

# DNS Alias Record pointing to Load Balancer
dns_alias_record = route53.Record("dnsRecord",
                                zone_id=hosted_zone_id,
                                name=domain_name,
                                type="A",
                                aliases=[{
                                    "name": load_balancer.dns_name,
                                    "zone_id": load_balancer.zone_id,
                                    "evaluate_target_health": True,
                                }],
                                )
# Outputs
pulumi.export("vpc_id", vpc.id)
pulumi.export("public_subnets", [subnet.id for subnet in public_subnets])
pulumi.export("private_subnets", [subnet.id for subnet in private_subnets])
pulumi.export("auto_scaling_group_name", auto_scaling_group.name)
pulumi.export("scale_up_policy_arn", scale_up_policy.arn)
pulumi.export("scale_down_policy_arn", scale_down_policy.arn)
pulumi.export("load_balancer_dns_name", load_balancer.dns_name)
pulumi.export("dns_record", dns_alias_record.name)
