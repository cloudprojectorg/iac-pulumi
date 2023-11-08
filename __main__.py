import pulumi
from pulumi_aws import ec2, get_availability_zones, rds, route53, iam
from pulumi import Config
import ipaddress
from pulumi import export
import json
import pulumi_aws as aws

# Create a Config instance
config = Config()

# Resource Tag
common_tag = {"Name": "my-pulumi-infra"}

# Fetch configurations
vpc_name = config.require("my_vpc_name")
vpc_cidr = config.require("my_vpc_cidr")
vpc_internet_gateway = config.require("my_internet_gateway")
# public_route_table_name = config.require("my_public_route_table")
# private_route_table_name = config.require("my_private_route_table")
mailgun_domain = config.require("mailgun_domain")
mailgun_sender = config.require("mailgun_sender")
ses_region = config.require("ses_region")
ses_sender = config.require("ses_sender")
api_key = config.require_secret('api_key')

# Calculate CIDR blocks for subnets
network = ipaddress.ip_network(vpc_cidr)
all_subnets = list(network.subnets(new_prefix=24))
subnets = all_subnets[1:]

# Split into public and private subnets
public_subnets_cidr = subnets[:3]
private_subnets_cidr = subnets[3:6]

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
num_azs = min(len(azs), 3)  # Use a maximum of 3 AZs

# Create Public Subnets
public_subnets = []
for i in range(1, num_azs+1):  # Start loop from 1
    subnet = ec2.Subnet(f"publicSubnet-{i}",
                        vpc_id=vpc.id,
                        cidr_block=str(public_subnets_cidr[i-1]),
                        availability_zone=azs[i-1],
                        map_public_ip_on_launch=True,
                        tags={**common_tag, "Type": f"publicSubnet-{i}"})
    public_subnets.append(subnet)

# Create Private Subnets
private_subnets = []
for i in range(4, 4+num_azs):  # Start loop from 4
    subnet = ec2.Subnet(f"privateSubnet-{i}",
                        vpc_id=vpc.id,
                        cidr_block=str(private_subnets_cidr[i-4]),
                        availability_zone=azs[i-4],
                        tags={**common_tag, "Type": f"privateSubnet-{i}"})
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

# Application Security Group
application_sg = ec2.SecurityGroup("applicationSecurityGroup",
                                   vpc_id=vpc.id,
                                   description="Security group for application server",
                                   ingress=[
                                       ec2.SecurityGroupIngressArgs(
                                           protocol="tcp",
                                           from_port=22,
                                           to_port=22,
                                           cidr_blocks=["0.0.0.0/0"]
                                       ),
                                       ec2.SecurityGroupIngressArgs(
                                           protocol="tcp",
                                           from_port=80,
                                           to_port=80,
                                           cidr_blocks=["0.0.0.0/0"]
                                       ),
                                       ec2.SecurityGroupIngressArgs(
                                           protocol="tcp",
                                           from_port=443,
                                           to_port=443,
                                           cidr_blocks=["0.0.0.0/0"]
                                       ),
                                       ec2.SecurityGroupIngressArgs(
                                           protocol="tcp",
                                           from_port=8080,
                                           to_port=8080,
                                           cidr_blocks=["0.0.0.0/0"]
                                       ),
                                       # Add other ports for your application as necessary
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
                            tags={**common_tag, "Type": "RDSInstance"})

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

# Function to generate the user data script
def generate_user_data_script(hostname, endpoint, db_password, api_key, mailgun_domain, mailgun_sender, ses_region, ses_sender):
    # hostname = endpoint.split(":")[0]

    return f"""#!/bin/bash
    set -e
    echo "User data script started to execute" | sudo tee -a /var/log/cloud-init-output.log

    # Wait/Retry Logic
    # for i in {{1..30}}; do
    #     mysql -h {hostname} -u root -p{db_password} -e 'SELECT 1' && break
    #     echo "Waiting for DB to be ready..." >> /var/log/userdata.log
    #     sleep 10
    # done

    # # Reload systemd and restart the service
    # sudo systemctl daemon-reload
    # sudo systemctl restart webapp.service

    # Write environment variables in separate file
    echo "DB_HOST={hostname}" | sudo tee -a /etc/webapp.env
    echo "DB_USERNAME=csye6225" | sudo tee -a /etc/webapp.env
    echo "DB_PASSWORD={db_password}" | sudo tee -a /etc/webapp.env
    echo "DB_NAME=csye6225" | sudo tee -a /etc/webapp.env
    echo "MAILGUN_API_KEY={api_key}" | sudo tee -a /etc/webapp.env
    echo "MAILGUN_DOMAIN={mailgun_domain}" | sudo tee -a /etc/webapp.env
    echo "MAILGUN_SENDER={mailgun_sender}" | sudo tee -a /etc/webapp.env

    # Configuration for SES
    # echo "SES_REGION=us-east-1" | sudo tee -a /etc/webapp.env
    # echo "SES_SENDER_EMAIL=noreply@example.com" | sudo tee -a /etc/webapp.env
    echo "SES_REGION={ses_region}" | sudo tee -a /etc/webapp.env
    echo "SES_SENDER_EMAIL={ses_sender}" | sudo tee -a /etc/webapp.env

    # Echo the environment variables to the log
    # cat /etc/webapp.env >> /var/log/userdata.log
    echo "DB_HOST=${hostname}" | sudo tee -a /var/log/userdata.log
    echo "DB_USERNAME=csye6225" | sudo tee -a /var/log/userdata.log
    echo "DB_NAME=csye6225" | sudo tee -a /var/log/userdata.log
    echo "MAILGUN_DOMAIN=${mailgun_domain}" | sudo tee -a /var/log/userdata.log
    echo "MAILGUN_SENDER=${mailgun_sender}" | sudo tee -a /var/log/userdata.log
    echo "SES_REGION=${ses_region}" | sudo tee -a /var/log/userdata.log
    echo "SES_SENDER_EMAIL=${ses_sender}" | sudo tee -a /var/log/userdata.log

    # Write Cloudwatch agent configuration to file
    sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/cloudwatch-config.json

    # Restart the Cloudwatch agent to apply configurations
    sudo systemctl enable amazon-cloudwatch-agent
    sudo systemctl restart amazon-cloudwatch-agent

    echo "User data script completed the execution" | sudo tee -a /var/log/cloud-init-output.log

    # Reload systemd 
    sudo systemctl daemon-reload

    # Introduce a delay before starting the service
    sleep 30
    sudo systemctl enable webapp.service
    sudo systemctl start webapp.service
    """

# Use the apply method to generate the user data script with the RDS endpoint and password
user_data_script = pulumi.Output.all(end_point, rds_instance.endpoint, config.require_secret("database_password"),config.require_secret('api_key'), 
                                     pulumi.Output.from_input(mailgun_domain), pulumi.Output.from_input(mailgun_sender),
                                     pulumi.Output.from_input(ses_region), pulumi.Output.from_input(ses_sender)).apply(lambda args: generate_user_data_script(*args))

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
ec2_instance = ec2.Instance("webInstance",
                            ami=ami_id,  
                            instance_type="t2.micro",
                            key_name="keypair_webapp",  
                            vpc_security_group_ids=[application_sg.id],
                            iam_instance_profile=profile_instance.name,
                            # Assuming launching in the first public subnet
                            subnet_id=public_subnets[0].id,
                            user_data=user_data_script,
                            opts=pulumi.ResourceOptions(
                                depends_on=[rds_instance]),
                            root_block_device=ec2.InstanceRootBlockDeviceArgs(
                                delete_on_termination=True,
                                volume_size=25,
                                volume_type="gp2"
                            ),
                            tags={**common_tag, "Type": "webInstance"}
                            )

# Access hosted zone ID and domain name from the configuration
hosted_zone_id = config.require("hosted_zone_id")
domain_name = config.require("domain_name")
public_ip = ec2_instance.public_ip # Get the public IP of the EC2 instance

# A type record
a_record = route53.Record("aTypeRecord",
                          name=domain_name,
                          type="A",
                          zone_id=hosted_zone_id,
                          ttl=60,
                          records=[public_ip])    

# Outputs
pulumi.export("vpc_id", vpc.id)
pulumi.export("public_subnets", [subnet.id for subnet in public_subnets])
pulumi.export("private_subnets", [subnet.id for subnet in private_subnets])
pulumi.export("web_instance_id", ec2_instance.id)
pulumi.export("rds_instance_endpoint", rds_instance.endpoint)
pulumi.export('database_password', config.require_secret("database_password"))
pulumi.export("web_instance_public_ip", ec2_instance.public_ip)
pulumi.export("dns_a_record", a_record.fqdn)
