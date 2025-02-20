import hashlib
import json
from urllib.parse import quote

import boto3


def get_name_hash(prefix: str, obj: dict, max_length: int = 128, hash_length: int = 12) -> str:
    prefix_length = min(max_length, len(prefix))
    if hash_length + prefix_length > max_length:
        msg = f"Prefix and hash length are too long: {prefix} has length {prefix_length}, hash length is {hash_length}, max length is {max_length}"
        raise ValueError(msg)
    return f"{prefix}-{hashlib.sha256(json.dumps(obj).encode()).hexdigest()[:hash_length]}"


def get_container_name(image_name: str) -> str:
    image_name_sanitized = "".join(c for c in image_name if c.isalnum() or c in "-_")
    if len(image_name_sanitized) <= 255:
        return image_name_sanitized
    return hashlib.sha256(image_name_sanitized.encode()).hexdigest()[:255]


def get_execution_role_arn(execution_role_prefix: str) -> str:
    iam_client = boto3.client("iam")

    trust_relationship = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}
        ],
    }

    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "secretsmanager:GetSecretValue",
                ],
                "Resource": [
                    "arn:aws:logs:*:*:log-group:/ecs/swe-rex-deployment:*",
                    "arn:aws:logs:*:*:log-group:/ecs/swe-rex-deployment",
                ],
            }
        ],
    }
    role_name = get_name_hash(execution_role_prefix, inline_policy, max_length=64)
    # Check if the role already exists
    role_exists = False
    try:
        role = iam_client.get_role(RoleName=role_name)
        role_exists = True
    except iam_client.exceptions.NoSuchEntityException:
        pass

    if not role_exists:
        role = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_relationship),
            Description="Execution role for ECS tasks",
            MaxSessionDuration=3600,
            Tags=[{"Key": "origin", "Value": "swe-rex-deployment-auto"}],
        )
    # check if policies already attached
    attached_policies = iam_client.list_attached_role_policies(RoleName=role_name)
    attached_policy_arns = [policy["PolicyArn"] for policy in attached_policies["AttachedPolicies"]]

    if "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" not in attached_policy_arns:
        iam_client.attach_role_policy(
            RoleName=role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
        )
    if "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly" not in attached_policy_arns:
        iam_client.attach_role_policy(
            RoleName=role_name, PolicyArn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
        )

    policy_names = iam_client.list_role_policies(RoleName=role_name)["PolicyNames"]
    if "LogsAndSecretsPolicy" not in policy_names:
        # Add inline policy
        iam_client.put_role_policy(
            RoleName=role_name, PolicyName="LogsAndSecretsPolicy", PolicyDocument=json.dumps(inline_policy)
        )
    waiter = iam_client.get_waiter("role_exists")
    waiter.wait(RoleName=role_name)
    return role["Role"]["Arn"]


def get_task_definition(
    image_name: str,
    port: int,
    execution_role_arn: str,
    task_definition_prefix: str,
    log_group: str | None = None,
) -> str:
    ecs_client = boto3.client("ecs")
    task_definition = {
        "executionRoleArn": execution_role_arn,
        "networkMode": "awsvpc",
        "memory": "2048",
        "cpu": "1 vCPU",
        "containerDefinitions": [
            {
                "name": get_container_name(image_name),
                "image": image_name,
                "portMappings": [{"containerPort": port, "hostPort": port, "protocol": "tcp"}],
                "essential": True,
                "entryPoint": ["/bin/sh", "-c"],
                "command": [
                    "echo 'hello world'"  # override command with run_task
                ],
            },
        ],
        "requiresCompatibilities": ["FARGATE", "EC2"],
    }
    if log_group:
        task_definition["containerDefinitions"][0]["logConfiguration"] = {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": log_group,
                "awslogs-region": "us-east-2",
                "awslogs-stream-prefix": "ecs",
                "awslogs-create-group": "true",
            },
        }
    family_name = get_name_hash(task_definition_prefix, task_definition, max_length=255)
    # if family exists just return the task definition
    try:
        response = ecs_client.describe_task_definition(taskDefinition=family_name)
        return response["taskDefinition"]
    except ecs_client.exceptions.ClientException:
        pass

    response = ecs_client.register_task_definition(
        family=family_name,
        **task_definition,
        tags=[{"key": "origin", "value": "swe-rex-deployment-auto"}],
    )
    return response["taskDefinition"]


def get_cluster_arn(cluster_name: str) -> str:
    ecs_client = boto3.client("ecs")
    response = ecs_client.create_cluster(
        clusterName=cluster_name,
        tags=[{"key": "origin", "value": "swe-rex-deployment-auto"}],
    )
    return response["cluster"]["clusterArn"]


def get_default_vpc_and_subnet() -> tuple[str, str]:
    ec2_client = boto3.client("ec2")
    vpcs = ec2_client.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
    if not vpcs["Vpcs"]:
        msg = "No default VPC found"
        raise Exception(msg)
    vpc_id = vpcs["Vpcs"][0]["VpcId"]
    subnets = ec2_client.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    if not subnets["Subnets"]:
        msg = "No subnets found in the default VPC"
        raise Exception(msg)
    subnet_id = subnets["Subnets"][0]["SubnetId"]
    return vpc_id, subnet_id


def get_security_group(vpc_id: str, port: int, security_group_prefix: str) -> str:
    ec2_client = boto3.client("ec2")
    inbound_rule = {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}
    # if it exists, just return the id
    security_group_name = get_name_hash(security_group_prefix, inbound_rule, max_length=255)
    try:
        security_group = ec2_client.describe_security_groups(GroupNames=[security_group_name])
        return security_group["SecurityGroups"][0]["GroupId"]
    except ec2_client.exceptions.ClientError:
        pass

    security_group = ec2_client.create_security_group(
        GroupName=security_group_name,
        Description="Security group swe rex",
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "security-group",
                "Tags": [{"Key": "origin", "Value": "swe-rex-deployment-auto"}],
            },
        ],
    )
    security_group_id = security_group["GroupId"]

    # Add an inbound rule to allow traffic on the port
    ec2_client.authorize_security_group_ingress(GroupId=security_group_id, IpPermissions=[inbound_rule])
    return security_group_id


def run_fargate_task(
    command: list[str],
    name: str,
    task_definition_arn: str,
    subnet_id: str,
    security_group_id: str,
    cluster_arn: str,
    vcpus: int = 1,
    memory: int = 2048,
    ephemeral_storage: int = 21,
    **fargate_args,
) -> str:
    run_task_args = {
        "taskDefinition": task_definition_arn,
        "launchType": "FARGATE",
        "cluster": cluster_arn,
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": [subnet_id],
                "securityGroups": [security_group_id],
                "assignPublicIp": "ENABLED",
            }
        },
        "propagateTags": "TASK_DEFINITION",
    }
    overrides = {
        "containerOverrides": [
            {
                "name": name,
                "command": command,
            },
        ],
        "cpu": f"{vcpus}vCPU",
        "memory": str(memory),
        "ephemeralStorage": {
            "sizeInGiB": ephemeral_storage,
        },
    }
    if fargate_args:
        overrides.update(fargate_args)

    if overrides:
        run_task_args["overrides"] = overrides

    ecs_client = boto3.client("ecs")
    response = ecs_client.run_task(
        **run_task_args,
        tags=[{"key": "origin", "value": "swe-rex-deployment-auto"}],
    )
    return response["tasks"][0]["taskArn"]


def get_public_ip(task_arn: str, cluster_arn: str) -> str:
    ecs_client = boto3.client("ecs")
    task_details = ecs_client.describe_tasks(cluster=cluster_arn, tasks=[task_arn])
    eni_id = task_details["tasks"][0]["attachments"][0]["details"][1]["value"]
    ec2_client = boto3.client("ec2")
    eni_details = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    return eni_details["NetworkInterfaces"][0]["Association"]["PublicIp"]


def get_cloudwatch_log_url(task_arn: str, task_definition: dict, container_name: str, region: str = "us-east-2") -> str:
    """
    Get the CloudWatch log URL for a running task.

    Args:
        task_arn (str): The ARN of the running task.
        task_definition (dict): The task definition for the running task.
        container_name (str): The name of the container in the task definition.

    Returns:
        str: The CloudWatch log URL.
    """
    container_def = task_definition["containerDefinitions"][0]
    log_config = container_def["logConfiguration"]["options"]
    log_group = log_config["awslogs-group"]
    task_id = task_arn.split("/")[-1]
    log_stream = f"{log_config['awslogs-stream-prefix']}/{container_name}/{task_id}"

    # Use %25 instead of $25 for encoding
    encoded_log_group = quote(log_group, safe="")
    encoded_log_stream = quote(log_stream, safe="")

    return (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}"
        f"#logsV2:log-groups/log-group/{encoded_log_group}"
        f"/log-events/{encoded_log_stream}"
    )
