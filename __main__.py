# import pulumi
# from pulumi_aws import ec2, get_availability_zones
# from pulumi import Config
# import ipaddress
# from pulumi import export


# # Create a Config instance
# config = Config()

# # Resource Tag
# common_tag = {"Name": "csye6225-infra-pulumi"}

# # Fetch configurations
# vpc_name = config.require("vpc_name")
# vpc_cidr = config.require("vpc_cidr")
# vpc_internet_gateway = config.require("internet_gateway")
# public_route_table_name = config.require("public_route_table")
# private_route_table_name = config.require("private_route_table")

# # Calculate CIDR blocks for subnets
# network = ipaddress.ip_network(vpc_cidr)
# all_subnets = list(network.subnets(new_prefix=24))
# subnets = all_subnets[1:]

# # Split into public and private subnets
# public_subnets_cidr = subnets[:3]
# private_subnets_cidr = subnets[3:6]

# # Create a VPC
# vpc = ec2.Vpc(vpc_name, cidr_block=vpc_cidr,
#               tags={**common_tag, "Type": "VPC"})

# # Create an Internet Gateway
# ig = ec2.InternetGateway("internetGateway", vpc_id=vpc.id,
#                          tags={**common_tag, "Type": "Internet Gateway"})

# # Get available AZs
# azs = get_availability_zones().names
# num_azs = min(len(azs), 3)  # Use a maximum of 3 AZs

# # Create Public Subnets
# public_subnets = []
# for i in range(1, num_azs+1):  # Start loop from 1
#     subnet = ec2.Subnet(f"publicSubnet-{i}",
#                         vpc_id=vpc.id,
#                         # Adjust the index
#                         cidr_block=str(public_subnets_cidr[i-1]),
#                         availability_zone=azs[i-1],  # Adjust the index
#                         map_public_ip_on_launch=True,
#                         tags={**common_tag, "Type": f"publicSubnet-{i}"})
#     public_subnets.append(subnet)


# # Create Private Subnets
# private_subnets = []
# for i in range(4, 4+num_azs):  # Start loop from 4
#     subnet = ec2.Subnet(f"privateSubnet-{i}",
#                         vpc_id=vpc.id,
#                         # Adjust the index
#                         cidr_block=str(private_subnets_cidr[i-4]),
#                         availability_zone=azs[i-4],  # Adjust the index
#                         tags={**common_tag, "Type": f"privateSubnet-{i}"})
#     private_subnets.append(subnet)


# # Create Public Route Table
# public_route_table = ec2.RouteTable(public_route_table_name, vpc_id=vpc.id, tags={
#                                     **common_tag, "Type": "publicRouteTable"})
# public_route = ec2.Route("publicRoute", route_table_id=public_route_table.id,
#                          destination_cidr_block="0.0.0.0/0", gateway_id=ig.id)

# # Associate Public Subnets to Public Route Table
# for i, subnet in enumerate(public_subnets):
#     ec2.RouteTableAssociation(
#         f"publicRta-{i}", route_table_id=public_route_table.id, subnet_id=subnet.id)

# # Create Private Route Table
# private_route_table = ec2.RouteTable(private_route_table_name, vpc_id=vpc.id, tags={
#                                      **common_tag, "Type": "privateRouteTable"})

# # Associate Private Subnets to Private Route Table
# for i, subnet in enumerate(private_subnets):
#     ec2.RouteTableAssociation(
#         f"privateRta-{i}", route_table_id=private_route_table.id, subnet_id=subnet.id)


import pulumi
from pulumi_aws import ec2, get_availability_zones
from pulumi import Config
import ipaddress
from pulumi import export

# Create a Config instance
config = Config()

# Resource Tag
custom_tag = {"Name": "my-pulumi-infra"}

# Fetch configurations
vpc_name = config.require("my_vpc_name")
vpc_cidr = config.require("my_vpc_cidr")
vpc_internet_gateway = config.require("my_internet_gateway")
public_route_table_name = config.require("my_public_route_table")
private_route_table_name = config.require("my_private_route_table")

# Calculate CIDR blocks for subnets
network = ipaddress.ip_network(vpc_cidr)
all_subnets = list(network.subnets(new_prefix=24))
subnets = all_subnets[1:]

# Split into public and private subnets
public_subnets_cidr = subnets[:3]
private_subnets_cidr = subnets[3:6]

# Create a VPC
vpc = ec2.Vpc("MyVpc", cidr_block=vpc_cidr,
              tags={**custom_tag, "Type": "VPC"})

# Create an Internet Gateway
ig = ec2.InternetGateway("MyInternetGateway", vpc_id=vpc.id,
                         tags={**custom_tag, "Type": "Internet Gateway"})

# Get available AZs
azs = get_availability_zones().names
num_azs = min(len(azs), 3)  # Use a maximum of 3 AZs

# Create Public Subnets
public_subnets = []
for i in range(1, num_azs+1):  # Start loop from 1
    subnet = ec2.Subnet(f"MyPublicSubnet{i}",
                        vpc_id=vpc.id,
                        # Adjust the index
                        cidr_block=str(public_subnets_cidr[i-1]),
                        availability_zone=azs[i-1],  # Adjust the index
                        map_public_ip_on_launch=True,
                        tags={**custom_tag, "Type": f"Public Subnet {i}"})
    public_subnets.append(subnet)

# Create Private Subnets
private_subnets = []
for i in range(4, 4+num_azs):  # Start loop from 4
    subnet = ec2.Subnet(f"MyPrivateSubnet{i}",
                        vpc_id=vpc.id,
                        # Adjust the index
                        cidr_block=str(private_subnets_cidr[i-4]),
                        availability_zone=azs[i-4],  # Adjust the index
                        tags={**custom_tag, "Type": f"Private Subnet {i}"})
    private_subnets.append(subnet)

# Create Public Route Table
public_route_table = ec2.RouteTable(
    "MyPublicRouteTable", vpc_id=vpc.id, tags={**custom_tag, "Type": "Public Route Table"})
public_route = ec2.Route("MyPublicRoute", route_table_id=public_route_table.id,
                         destination_cidr_block="0.0.0.0/0", gateway_id=ig.id)

# Associate Public Subnets to Public Route Table
for i, subnet in enumerate(public_subnets):
    ec2.RouteTableAssociation(
        f"MyPublicRouteAssociation{i}", route_table_id=public_route_table.id, subnet_id=subnet.id)

# Create Private Route Table
private_route_table = ec2.RouteTable(
    "MyPrivateRouteTable", vpc_id=vpc.id, tags={**custom_tag, "Type": "Private Route Table"})

# Associate Private Subnets to Private Route Table
for i, subnet in enumerate(private_subnets):
    ec2.RouteTableAssociation(
        f"MyPrivateRouteAssociation{i}", route_table_id=private_route_table.id, subnet_id=subnet.id)
