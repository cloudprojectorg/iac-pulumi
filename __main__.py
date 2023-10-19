import pulumi
from pulumi_aws import ec2, get_availability_zones
from pulumi import Config
import ipaddress
from pulumi import export

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

# Calculate CIDR blocks for subnets
network = ipaddress.ip_network(vpc_cidr)
all_subnets = list(network.subnets(new_prefix=24))
subnets = all_subnets[1:]

# Split into public and private subnets
public_subnets_cidr = subnets[:3]
private_subnets_cidr = subnets[3:6]

# Create a VPC
vpc = ec2.Vpc(vpc_name, cidr_block=vpc_cidr,
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
                                   description="Security group for application servers",
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
                                   tags={**common_tag,
                                         "Type": "applicationSecurityGroup"}
                                   )

# EC2 Instance
ami_id = config.require("ami_id")  
ec2_instance = ec2.Instance("webInstance",
                            ami=ami_id,  # Custom AMI ID
                            instance_type="t2.micro",
                            key_name="ec2-ami-key",  # Replace with your key pair
                            vpc_security_group_ids=[application_sg.id],
                            # Assuming launching in the first public subnet
                            subnet_id=public_subnets[0].id,
                            root_block_device=ec2.InstanceRootBlockDeviceArgs(
                                delete_on_termination=True,
                                volume_size=25,
                                volume_type="gp2"
                            ),
                            tags={**common_tag, "Type": "webInstance"}
                            )

# Outputs
pulumi.export("vpc_id", vpc.id)
pulumi.export("public_subnets", [subnet.id for subnet in public_subnets])
pulumi.export("private_subnets", [subnet.id for subnet in private_subnets])
pulumi.export("web_instance_id", ec2_instance.id)
