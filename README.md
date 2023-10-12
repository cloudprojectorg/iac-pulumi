# AWS Infrastructure as Code with Pulumi

This repository contains Infrastructure as Code (IAC) written in Python using Pulumi to provision AWS resources, including a Virtual Private Cloud (VPC), subnets, route tables, and an Internet Gateway. The code is designed to create a basic network infrastructure.

## Prerequisites

Before you begin, ensure you have the following prerequisites:

- [Pulumi CLI](https://www.pulumi.com/docs/get-started/install/)
- [Python](https://www.python.org/) (Pulumi uses Python for this example)
- An AWS account and AWS CLI configured with necessary credentials

## Getting Started

1. Clone this repository to your local machine:

   git clone https://github.com/yourusername/aws-pulumi-network.git
   cd aws-pulumi-network

##Set up a Python virtual environment and install dependencies:


python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
pip install -r requirements.txt

##Initialize a new Pulumi stack:

pulumi stack init my-pulumi-stack

##Configure your Pulumi stack with necessary variables:

pulumi config set my_vpc_name "MyVPC"
pulumi config set my_vpc_cidr "10.0.0.0/16"
pulumi config set my_internet_gateway "MyInternetGateway"
pulumi config set my_public_route_table "MyPublicRouteTable"
pulumi config set my_private_route_table "MyPrivateRouteTable"

##Create your AWS infrastructure using Pulumi:

pulumi up

##Review the changes, and if everything looks good, confirm by typing yes. Pulumi will create the specified resources on AWS.
Once the deployment is complete, you can find the information about your resources in the Pulumi stack outputs.

pulumi stack output

##To clean up and delete the AWS resources, run:
pulumi destroy

##Project Structure
Pulumi.yaml: The Pulumi project configuration file.
Pulumi.dev.yaml: The Pulumi stack configuration file for the development environment.
main.py: The Pulumi program file, containing the code to create AWS resources.
requirements.txt: Python dependencies for the project.
README.md: This documentation file.