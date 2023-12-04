import pulumi
from pulumi_aws import ec2, get_availability_zones, rds, route53, iam
from pulumi import Config
import ipaddress
from pulumi import export
import json
import pulumi_aws as aws
import base64
from pulumi_gcp import serviceaccount
from pulumi_aws import get_caller_identity
from pulumi_aws import get_region
from pulumi_gcp import storage
from pulumi_aws import lambda_
from pulumi_aws import sns

# Create a Config instance
config = Config()
account_id = get_caller_identity().account_id
region = get_region()
ami_owner = config.require("ami_owner")

# Fetch the ACM certificate's ARN for your domain
certificate_domain = config.require("certificate_domain")
selected_certificate = aws.acm.get_certificate(domain=certificate_domain)

# Resource Tag
common_tag = {"Name": "my-pulumi-infra"}
common_tag_low = {k.lower(): v for k, v in common_tag.items()}

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

# Get the Mailgun API key from the config
mailgun_api_key_value = config.require_secret("mailgun_api_key")

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
    
# Google Cloud Storage Bucket
bucket_gcs = storage.Bucket('bucket_submission_github',
                            name='bucket-submission-github',
                            location='US',
                            storage_class='STANDARD',
                            versioning=storage.BucketVersioningArgs(
                                enabled=True),
                            uniform_bucket_level_access=True,
                            labels=common_tag_low,
                            force_destroy=True)    

# Google Service Account
service_account_gcp = serviceaccount.Account('service_account',
                                             account_id='submission-service-account',
                                             display_name='Submission Service Account',
                                             project=config.require("gcp_project"))

# Google Service Account Keys
service_account_keys_gcs = serviceaccount.Key('service_account_keys',
                                              service_account_id=service_account_gcp.name,
                                              public_key_type='TYPE_X509_PEM_FILE',
                                              opts=pulumi.ResourceOptions(depends_on=[service_account_gcp]))

# Grant the Storage Admin role to the service account
service_account_iam_binding_gcs = storage.BucketIAMBinding('service_account_storage_admin',
                                                           bucket=bucket_gcs.name,
                                                           role='roles/storage.admin',
                                                           members=[pulumi.Output.concat("serviceAccount:", service_account_gcp.email)],
                                                           opts=pulumi.ResourceOptions(depends_on=[service_account_gcp]))

# Save the Service Account key in AWS Secrets Manager
service_account_secret = aws.secretsmanager.Secret("gcpServiceAccountKey",
                                                   description="GCP Service Account Key")

service_account_secret_value = aws.secretsmanager.SecretVersion("gcpServiceAccountKeyValue",
                                                                secret_id=service_account_secret.id,
                                                                secret_string=service_account_keys_gcs.private_key.apply(
                                                                    lambda key: base64.b64decode(key).decode('utf-8') if key else None),
                                                                opts=pulumi.ResourceOptions(depends_on=[service_account_secret, service_account_keys_gcs]))

# Secrets for DynamoDB table, SES email identity, and SES domain
table_secret_dynamodb = aws.secretsmanager.Secret("DynamoDbTableSecret",
                                                  description="DynamoDB table name for the email tracking")

email_identity_secret_ses = aws.secretsmanager.Secret("SesEmailIdentitySecret",
                                                      description="SES email identity for the Lambda function")

domain_secret_ses = aws.secretsmanager.Secret("SesDomainSecret",
                                              description="SES domain for the Lambda function")

bucket_name_secret_gcs = aws.secretsmanager.Secret("gcsBucketNameSecret",
                                                   description="GCS bucket name for file uploads")

# Secret values
table_secret_value_dynamodb = aws.secretsmanager.SecretVersion("DynamoDbTableSecretValue",
                                                               secret_id=table_secret_dynamodb.id,
                                                               secret_string=config.require("dynamo_db_table"))

email_identity_secret_value_ses = aws.secretsmanager.SecretVersion("SesEmailIdentitySecretValue",
                                                                   secret_id=email_identity_secret_ses.id,
                                                                   secret_string=config.require("mailgun_sender"))

domain_secret_value_ses = aws.secretsmanager.SecretVersion("SesDomainSecretValue",
                                                           secret_id=domain_secret_ses.id,
                                                           secret_string=config.require("mailgun_domain"))

bucket_name_secret_value_gcs = aws.secretsmanager.SecretVersion("gcsBucketNameSecretValue",
                                                                secret_id=bucket_name_secret_gcs.id,
                                                                secret_string=bucket_gcs.name.apply(
                                                                    lambda name: json.dumps({"gcs_bucket_name": name})),
                                                                opts=pulumi.ResourceOptions(depends_on=[bucket_name_secret_gcs]))

mailgun_api_key_secret = aws.secretsmanager.Secret("mailgunApiKey",
                                                   description="Mailgun API Key")

mailgun_api_key_secret_value = aws.secretsmanager.SecretVersion("mailgunApiKeyValue",
                                                                secret_id=mailgun_api_key_secret.id,
                                                                secret_string=mailgun_api_key_value)

mailgun_domain_secret = aws.secretsmanager.Secret("mailgunDomain",
                                                  description="Mailgun Domain")

mailgun_domain_secret_value = aws.secretsmanager.SecretVersion("mailgunDomainValue",
                                                               secret_id=mailgun_domain_secret.id,
                                                               secret_string=config.require("mailgun_domain"))

# Create an SNS topic
sns_topic = aws.sns.Topic('assignmentSubmissionTopic',
                          display_name='Assignment Submission Notifications')

# DynamoDB Table for Email Tracking
email_tracking_table = aws.dynamodb.Table('EmailTrackingTable',
                                          attributes=[
                                              aws.dynamodb.TableAttributeArgs(
                                                  # This should be the unique identifier for the request
                                                  name='RequestId',  
                                                  # 'S' stands for string, which is suitable for an ID
                                                  type='S',  
                                              ),
                                          ],
                                          billing_mode='PAY_PER_REQUEST',
                                          hash_key='RequestId',
                                          name="EmailTrackingTable",
                                          tags={
                                              'Name': 'EmailTracking',
                                              **common_tag,})

# IAM Role for Lambda Function
role_lambda = iam.Role('lambdaRole',
                       assume_role_policy=json.dumps({
                           "Version": "2012-10-17",
                           "Statement": [{
                               "Action": "sts:AssumeRole",
                               "Effect": "Allow",
                               "Principal": {
                                   "Service": "lambda.amazonaws.com"
                               }
                           }]
                       }))

# Define the policy with the necessary permissions for managing AMIs, Launch Templates, and AutoScaling Groups
ami_launch_policy_json = json.dumps({
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeImages",
                "ec2:DescribeLaunchTemplates",
                "ec2:CreateLaunchTemplate",
                "ec2:CreateLaunchTemplateVersion",
                "autoscaling:CreateAutoScalingGroup",
                "autoscaling:UpdateAutoScalingGroup",
                "autoscaling:DescribeAutoScalingGroups"
            ],
            "Resource": "*"
        }
    ]
})

# Create the IAM policy resource
ami_launch_policy = aws.iam.Policy("amiLaunchPolicy",
                                   description="Policy for AMI and Launch Template management",
                                   policy=ami_launch_policy_json)

# Attach the policy to the IAM Role
ami_launch_policy_attachment = aws.iam.RolePolicyAttachment("amiLaunchPolicyAttachment",
                                                            role=role_lambda.name,
                                                            policy_arn=ami_launch_policy.arn)

# Define the AWSLambdaBasicExecutionRole policy
lambda_execution_policy = iam.Policy("lambdaExecutionPolicy",
                                     description="AWS Lambda Basic Execution Role",
                                     policy=json.dumps({
                                         "Version": "2012-10-17",
                                         "Statement": [{
                                            "Effect": "Allow",
                                            "Action": [
                                                 "logs:CreateLogGroup",
                                                 "logs:CreateLogStream",
                                                 "logs:PutLogEvents"
                                            ],
                                             "Resource": "arn:aws:logs:::*"
                                         },
                                         {
                                            "Effect": "Allow",
                                            "Action": "logs:CreateLogGroup",
                                            "Resource": "arn:aws:logs:us-east-1:949500228056:*"
                                         },
                                         {
                                            "Effect": "Allow",
                                            "Action": [
                                                "logs:CreateLogStream",
                                                "logs:PutLogEvents"
                                            ],
                                            "Resource": [
                                                "arn:aws:logs:us-east-1:949500228056:log-group:/aws/lambda/AssignmentSubmissionHandler:*"
                                            ]
                                        }
                                         ]
                                     }))

# Attach the custom policy to the lambdaRole
lambda_execution_policy_attachment = iam.RolePolicyAttachment("lambdaExecutionPolicyAttachment",
                                                              role=role_lambda.name,
                                                              policy_arn=lambda_execution_policy.arn)

caller_identity = aws.get_caller_identity()
aws_region = aws.get_region()
resource_string = f"arn:aws:logs:{region.name}:{account_id}:*"

policy_document_json = pulumi.Output.all(
                                        region=region.name,
                                        account_id=account_id,
                                        sns_topic_arn=sns_topic.arn,
                                        email_tracking_table_arn=email_tracking_table.arn,
                                        dynamodb_table_secret_arn=table_secret_dynamodb.arn,
                                        ses_email_identity_secret_arn=email_identity_secret_ses.arn,
                                        mailgun_email_identity_secret_arn=mailgun_api_key_secret.arn,
                                        mailgun_domian_secret_arn=mailgun_domain_secret.arn,
                                        ses_domain_secret_arn=domain_secret_ses.arn,
                                        service_account_secret_arn=service_account_secret.arn,
                                        gcs_bucket_name_secret_arn=bucket_name_secret_gcs.arn,
                                        ).apply(lambda args: json.dumps({
                                            "Version": "2012-10-17",
                                            "Statement": [
                                                {
                                                    "Effect": "Allow",
                                                    "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                                                    "Resource": resource_string  
                                                },
                                                {
                                                    "Effect": "Allow",
                                                    "Action": "sns:Publish",
                                                    "Resource": args['sns_topic_arn']
                                                },
                                                {
                                                    "Effect": "Allow",
                                                    "Action": [
                                                        "dynamodb:GetItem",
                                                        "dynamodb:PutItem",
                                                        "dynamodb:UpdateItem",
                                                        "dynamodb:DeleteItem",
                                                        "dynamodb:Scan",
                                                        "dynamodb:Query"
                                                    ],
                                                    "Resource": args['email_tracking_table_arn']
                                                },
                                                {
                                                    "Effect": "Allow",
                                                    "Action": [
                                                        "ses:SendEmail",
                                                        "ses:SendRawEmail"
                                                    ],
                                                    "Resource": "*"
                                                },
                                                {
                                                    "Effect": "Allow",
                                                    "Action": "secretsmanager:GetSecretValue",
                                                    # Here we must construct the list manually using keys
                                                    "Resource": [
                                                        args['dynamodb_table_secret_arn'],
                                                        args['ses_email_identity_secret_arn'],
                                                        args['ses_domain_secret_arn'],
                                                        args['service_account_secret_arn'],
                                                        args['gcs_bucket_name_secret_arn'],
                                                        args['mailgun_email_identity_secret_arn'],
                                                        args['mailgun_domian_secret_arn']
                                                    ]
                                                }
                                            ]}, indent=4))

# Use the policy document to create the IAM policy resource
iam_policy_lambda = policy_document_json.apply(lambda policy_json: aws.iam.Policy(
                                            "LambdaIAMPolicy",
                                            description="IAM Policy for Lambda to interact with other services",
                                            policy=policy_json,
                                            opts=pulumi.ResourceOptions(delete_before_replace=True)
                                        ))

iam_policy_arn_lambda = iam_policy_lambda.arn.apply(lambda arn: arn)

# Attach the IAM policy to the Lambda execution role
iam_policy_attachment_lambda = pulumi.Output.all(iam_policy_arn_lambda, role_lambda.name).apply(lambda args: aws.iam.RolePolicyAttachment(
                                                "LambdaIAMPolicyAttachment",
                                                role=args[1],
                                                policy_arn=args[0],
                                                opts=pulumi.ResourceOptions(delete_before_replace=True)
                                            ))

absolute_path_to_zip = "C:/Users/Shinde/Documents/Anuja/MSIS_CourseWork/Semester3/CloudMain/Assignment9/function.zip"


code = pulumi.AssetArchive({
    '.': pulumi.FileArchive(absolute_path_to_zip)
})

# Lambda Function
lambda_function = lambda_.Function('submissionLambda',
                                   role=role_lambda.arn,
                                   runtime='python3.8',
                                   handler='serverless.handler_lambda',
                                   code=code,
                                   environment={
                                       'variables': {
                                           'GCS_BUCKET_SECRET_ARN': bucket_name_secret_gcs.arn,
                                           'SES_REGION': ses_region,
                                           'DYNAMODB_TABLE_SECRET_ARN': table_secret_dynamodb.arn,
                                           'MAILGUN_API_KEY_SECRET_ARN': mailgun_api_key_secret.arn,
                                           'MAILGUN_DOMAIN_SECRET_ARN': mailgun_domain_secret.arn,
                                           'SES_EMAIL_IDENTITY_SECRET_ARN': email_identity_secret_ses.arn,
                                           'SES_DOMAIN_SECRET_ARN': domain_secret_ses.arn,
                                           'GCP_SERVICE_ACCOUNT_SECRET_ARN': service_account_secret.arn,
                                       }
                                   },
                                   timeout=60,
                                   opts=pulumi.ResourceOptions(depends_on=[iam_policy_attachment_lambda]))

invoke_policy_lambda = iam.Policy("lambdaInvokePolicy",
                                  policy=pulumi.Output.all(sns_topic.arn).apply(lambda arn: json.dumps({
                                      "Version": "2012-10-17",
                                      "Statement": [{
                                          "Effect": "Allow",
                                          "Action": "lambda:InvokeFunction",
                                          "Resource": "*",
                                          "Condition": {
                                              "ArnLike": {
                                                  "AWS:SourceArn": arn
                                              }
                                          }
                                      }]
                                  })))

invoke_policy_attachment_lambda = iam.RolePolicyAttachment("lambdaInvokePolicyAttachment",
                                                           role=role_lambda.name,
                                                           policy_arn=invoke_policy_lambda.arn)

# Permission for the SNS Topic to invoke the Lambda function
permission_lambda = lambda_.Permission("lambdaPermission",
                                       action="lambda:InvokeFunction",
                                       function=lambda_function.arn,
                                       principal="sns.amazonaws.com",
                                       source_arn=sns_topic.arn,
                                       opts=pulumi.ResourceOptions(depends_on=[lambda_function]))

# SNS Topic Subscription to the Lambda function
topic_subscription_sns = sns.TopicSubscription("snsTopicSubscription",
                                               topic=sns_topic.arn,
                                               protocol="lambda",
                                               endpoint=lambda_function.arn,
                                               opts=pulumi.ResourceOptions(depends_on=[permission_lambda]))
    
# Load balancer Security Group
load_balancer_sg = ec2.SecurityGroup('loadBalancerSecurityGroup',
                                     vpc_id=vpc.id,
                                     description='Security group for load balancer',
                                     ingress=[
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
                           port=443,
                           protocol="HTTPS",
                           ssl_policy="ELBSecurityPolicy-2016-08",
                           certificate_arn=selected_certificate.arn,  # SSL Certificate ARN
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
sns_topic_arn = sns_topic.arn

# Function to generate the user data script
def generate_user_data_script(hostname, password, sns_topic_arn):
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

    # Set the SNS topic ARN as an environment variable
    echo "SNS_TOPIC_ARN={sns_topic_arn}" | sudo tee -a /etc/webapp.env
    echo "SNS_TOPIC_ARN={sns_topic_arn}" | sudo tee -a /var/log/userdata.log

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
user_data_script = pulumi.Output.all(end_point, database_password, sns_topic_arn).apply(
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
# ami_id = config.require("ami_id")  

latest_ami = ec2.get_ami(most_recent=True,
                         owners=[ami_owner],
                         filters=[{"name": "name", "values": ["my-custom-ami-*"]}])

# Use the latest AMI ID
ami_id = latest_ami.id

# ami = ec2.get_ami(most_recent=True,
#                   owners=["amazon"],
#                   filters=[{"name":"name","values":["amzn2-ami-hvm-*-x86_64-gp2"]}])

ec2_launch_template = ec2.LaunchTemplate('launchTemplate',
                                        name='web-app-launch-template',
                                        image_id=ami_id,
                                        instance_type="t2.micro",
                                        key_name="keypair_webapp",
                                        network_interfaces=[{
                                            'associate_public_ip_address': True,
                                            'security_groups': [application_sg.id]
                                        }],
                                        block_device_mappings=[{
                                            'device_name': latest_ami.root_device_name,
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
                                           name='auto-scaling-group',
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
pulumi.export("scale_up_policy_arn", scale_up_policy.arn)
pulumi.export("scale_down_policy_arn", scale_down_policy.arn)
pulumi.export("load_balancer_dns_name", load_balancer.dns_name)
pulumi.export("dns_record", dns_alias_record.name)
pulumi.export('sns_topic_arn', sns_topic.arn)
pulumi.export('gcs_bucket_name', bucket_gcs.name)
pulumi.export('gcs_service_account_key', service_account_keys_gcs.private_key)
pulumi.export('lambda_function_arn', lambda_function.arn)
pulumi.export('email_tracking_table_name', email_tracking_table.name)
pulumi.export('sns_topic_subscription_arn', topic_subscription_sns.id)
pulumi.export('lambda_execution_policy.arn', lambda_execution_policy.arn)
