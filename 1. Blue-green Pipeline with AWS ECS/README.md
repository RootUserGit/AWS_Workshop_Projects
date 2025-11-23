# AWS Community Day Workshop: Building Your First DevOps Blue/Green Pipeline with ECS

This workshop guides you through building a Blue-Green deployment pipeline with AWS CodePipeline that deploys on AWS ECS with EC2. This deployment strategy helps teams test applications while routing traffic to a non-production route, and when confirmed that the app functions as expected, the traffic is routed to production. In case of any failure, a rollback is initiated for the previously working version, avoiding downtime.

## Table of Contents
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Step-by-Step Setup](#step-by-step-setup)
- [DevOps Pipeline in Action](#devops-pipeline-in-action)
- [Clean-up](#clean-up)
- [Reference](#reference)

## Architecture

### App Flow
The infrastructure consists of:
- **Application Load Balancer (ALB)** - Exposes the app on Port 80, routes traffic to the autoscaling group managed by ECS
- **ECS with EC2** - Fleet of EC2 instances running in two AZs for high availability
- **ECS Agent** - Installed on each instance with necessary software for running Docker containers
- **Aurora PostgreSQL (RDS)** - Data storage with replication in another availability zone for resilience
- **Auto-scaling** - ECS launches additional containers during traffic spikes

### Deployment Flow
The CI/CD pipeline automates deployment:
1. Developers push code changes to GitLab
2. AWS CodePipeline is triggered via connection app (authenticated to GitLab)
3. CodeBuild builds, containerizes, and pushes the image to ECR
4. CodeDeploy deploys the new app:
   - First deploys with port 8080 for testing
   - Team can approve traffic switch to newly deployed container
   - Former containers can be configured to run for some time during testing
   - If everything is fine, the last version of the deployed app can be terminated

## Prerequisites

- **Code Editor**: VSCode or similar
- **GitLab Account**: For code repository
- **AWS Account**: With appropriate permissions (full access to RDS, ECS, ECR, IAM, CodePipeline, CodeBuild, CodeDeploy)
- **AWS CLI**: Configured with access keys
- **Local Development Environment**: Terminal access (Linux/WSL/macOS)

## Step-by-Step Setup

### 1. Clone and Setup Code

```bash
git clone https://gitlab.com/ndzenyuy/tripmgmt.git
cd tripmgmt
rm -rf .git
git init
code .
```

Create a new GitLab repository named "tripmgmt" (public, without README), then push the code:

```bash
git remote add origin <your-repo-url>
git add .
git commit -m "Initial commit"
git push --set-upstream origin main
```

### 2. Create Required AWS IAM Roles

#### Task Execution Role (`ecsTaskExecutionRole`)
Grants Amazon ECS container and Fargate agents permission to make AWS API calls.

1. Open IAM console
2. Navigate to Roles → Create role
3. Select **AWS Service** as Trusted entity type
4. Use case: **Elastic Container Service** → **Elastic Container Service Task**
5. Attach policy: `AmazonECSTaskExecutionRolePolicy`
6. Name: `ecsTaskExecutionRole`
7. Save the Role ARN for later use

#### ECS Container Instance Role (`ecsInstanceRole`)
Required for EC2 launch type.

1. Create role → **AWS Service** → **EC2**
2. Attach policy: `AmazonEC2ContainerServiceforEC2Role`
3. Name: `ecsInstanceRole`

#### ECS CodeDeploy Role (`ecsCodeDeployRole`)
Provides CodeDeploy permissions to update ECS service.

1. Create role → **AWS Service** → **CodeDeploy**
2. Use case: **CodeDeploy - ECS**
3. Attach policy: `AWSCodeDeployRoleForECS`
4. Name: `ecsCodeDeployRole`

### 3. Setup Aurora PostgreSQL Database

1. Open RDS console → Create database
2. Engine: **Aurora (PostgreSQL Compatible)**
3. Templates: **Dev/Test** (for cost optimization)
4. DB cluster identifier: `tripmgmt-dbcluster`
5. Credentials:
   - Master username: `postgres`
   - Master password: `postgres123`
6. Instance: `db.t3.medium` or `db.t4g.medium` (graviton)
7. VPC: Default VPC
8. Public access: **Yes**
9. Security group: Create new `tripmgmt-dbcluster-sg`
   - Add inbound rule: PostgreSQL (5432) from Anywhere IPv4
10. Additional configuration:
    - Initial database name: `tripmgmt`
11. Create database
12. Note the Writer endpoint for later use

### 4. Create Elastic Container Registry (ECR)

1. Open ECR console → Create repository
2. Visibility: **Private**
3. Repository name: `tripmgmt-demo`
4. Tag immutability: **Enabled**
5. Scan on push: **Enabled**
6. Create repository
7. Save the repository URI

### 5. Setup Elastic Container Service (ECS)

#### Create ECS Cluster
1. Open ECS console → Clusters → Create Cluster
2. Cluster name: `tripmgmt-demo-cluster`
3. Infrastructure:
   - **Amazon EC2 instances**
   - Provisioning model: **On-Demand**
   - OS: **Amazon Linux 2**
   - EC2 instance type: `t3.small`
   - Desired capacity: Min=2, Max=4
   - SSH key pair: Select your key pair
4. Network settings: Default VPC, all subnets
5. Infrastructure role: `ecsInstanceRole`
6. Create cluster

#### Create Task Definition
1. ECS → Task Definitions → Create new Task Definition
2. Task definition family: `tripmgmt-demo-taskdef`
3. Launch type: **EC2**
4. Task role: `ecsTaskExecutionRole`
5. Task execution role: `ecsTaskExecutionRole`
6. Network mode: **bridge**
7. Task memory: `500 MiB`
8. Task CPU: `256 (.25 vCPU)`
9. Container:
   - Name: `tripmgmt-demo-container`
   - Image URI: `<your-ecr-repo-uri>:latest`
   - Port mappings: 
     - Container port: `8080`
     - Protocol: `tcp`
   - Environment variables:
     - `SPRING_DATASOURCE_URL`: `jdbc:postgresql://<rds-endpoint>:5432/tripmgmt`
     - `SPRING_DATASOURCE_USERNAME`: `postgres`
     - `SPRING_DATASOURCE_PASSWORD`: `postgres123`
10. Create task definition

### 6. Create Application Load Balancer

1. EC2 console → Load Balancers → Create Load Balancer
2. Type: **Application Load Balancer**
3. Name: `tripmgmt-demo-alb`
4. Scheme: **Internet-facing**
5. Network mapping: Default VPC, select all AZs
6. Security group: Create new
   - Name: `tripmgmt-alb-sg`
   - Inbound rules:
     - HTTP (80) from Anywhere IPv4
     - Custom TCP (8080) from Anywhere IPv4
7. Listeners:
   - **Listener 1**: HTTP:80 → Create target group
     - Target group name: `tripmgmt-prod-tg`
     - Target type: **Instance**
     - Protocol: HTTP, Port: 80
     - Health check path: `/`
   - **Listener 2**: HTTP:8080 → Create target group
     - Target group name: `tripmgmt-test-tg`
     - Target type: **Instance**
     - Protocol: HTTP, Port: 8080
     - Health check path: `/`
8. Create load balancer
9. Save the DNS name

### 7. Create ECS Service

1. ECS → Clusters → Select your cluster → Services → Create
2. Launch type: **EC2**
3. Task Definition: Select your task definition
4. Service name: `tripmgmt-demo-service`
5. Number of tasks: `2`
6. Deployment type: **Blue/green deployment (powered by AWS CodeDeploy)**
7. Service role: `ecsCodeDeployRole`
8. Load balancing:
   - Load balancer type: **Application Load Balancer**
   - Select your ALB
   - Production listener: **80:HTTP**
   - Test listener: **8080:HTTP**
   - Target group 1: `tripmgmt-prod-tg`
   - Target group 2: `tripmgmt-test-tg`
9. Create service

### 8. Build and Push Initial Docker Image

Update the `buildspec.yml` file with your ECR repository URI and RDS endpoint, then:

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <aws-account-id>.dkr.ecr.<region>.amazonaws.com

# Build Docker image
docker build -t tripmgmt-demo .

# Tag the image
docker tag tripmgmt-demo:latest <ecr-repo-uri>:latest

# Push to ECR
docker push <ecr-repo-uri>:latest
```

### 9. Setup AWS CodeBuild

1. CodeBuild console → Create build project
2. Project name: `codebuild-tripmgmt-demo`
3. Source:
   - Source provider: **GitLab**
   - Repository: **Repository in my GitLab account**
   - GitLab repository URL: Your repository URL
   - Source version: `main`
4. Environment:
   - Environment image: **Managed image**
   - OS: **Amazon Linux 2**
   - Runtime: **Standard**
   - Image: Latest
   - Privileged: **Enabled** (for Docker)
   - Service role: Create new or use existing
5. Environment variables:
   - `AWS_DEFAULT_REGION`: Your region
   - `AWS_ACCOUNT_ID`: Your account ID
   - `IMAGE_REPO_NAME`: `tripmgmt-demo`
   - `IMAGE_TAG`: `latest`
   - `SPRING_DATASOURCE_URL`: Your RDS endpoint
6. Buildspec: Use `buildspec.yml` from source
7. Create build project

### 10. Connect GitLab to AWS

1. CodePipeline console → Settings → Connections
2. Create connection
3. Provider: **GitLab**
4. Connection name: `gitlab-connection-tripmgmt`
5. Complete authorization with GitLab
6. Install AWS Connector app on GitLab

### 11. Create AWS CodeDeploy Application

#### Create Application
1. CodeDeploy console → Applications → Create application
2. Application name: `CodeDeploy-Tripmgmt-Demo-App`
3. Compute platform: **Amazon ECS**
4. Create application

#### Create Deployment Group
1. Application → Deployment groups → Create deployment group
2. Deployment group name: `deploygrp-tripmgmt-demo`
3. Service role: `ecsCodeDeployRole`
4. Environment configuration:
   - ECS cluster: `tripmgmt-demo-cluster`
   - ECS service: `tripmgmt-demo-service`
5. Load balancer:
   - Load balancer: Select your ALB
   - Production listener: **80:HTTP**
   - Test listener: **8080:HTTP**
   - Target group 1: `tripmgmt-prod-tg`
   - Target group 2: `tripmgmt-test-tg`
6. Deployment settings:
   - Reroute traffic: **0 days, 0 hours, 5 minutes** (wait time for verification)
   - Deployment configuration: **CodeDeployDefault.ECSAllAtOnce**
   - Original revision termination: **0 days, 0 hours, 0 minutes**
7. Create deployment group

### 12. Create AWS CodePipeline

1. CodePipeline console → Create pipeline
2. Pipeline settings:
   - Name: `codepipeline-tripmgmt-demo`
   - Service role: Create new
   - Role name: `codepipeline-tripmgmt-demo-service-role`
   - Artifact store: **Default location**
3. Source stage:
   - Source provider: **GitLab**
   - Connection: Select your GitLab connection
   - Repository: `tripmgmt`
   - Branch: `main`
   - Output artifact format: **CodePipeline default**
4. Build stage:
   - Build provider: **AWS CodeBuild**
   - Project name: `codebuild-tripmgmt-demo`
5. Skip test stage
6. Deploy stage:
   - Deploy provider: **Amazon ECS (Blue/Green)**
   - CodeDeploy application: `CodeDeploy-Tripmgmt-Demo-App`
   - Deployment group: `deploygrp-tripmgmt-demo`
   - Amazon ECS task definition: **BuildArtifact** → `taskdef.json`
   - AWS CodeDeploy AppSpec file: **BuildArtifact** → `appspec.yaml`
7. Create pipeline
8. **IMPORTANT**: Stop the pipeline execution immediately

#### Modify Deploy Stage
1. Edit pipeline → Edit Deploy stage
2. Edit Deploy action:
   - Input artifacts: Change from **BuildArtifact** to **SourceArtifact**
   - Task definition: **SourceArtifact** → `taskdef.json`
   - AppSpec file: **SourceArtifact** → `appspec.yaml`
3. Save changes

## DevOps Pipeline in Action

### Testing the Pipeline

1. **Make a visible change** to the application:
   - File: `src/main/webapp/app/home/home.component.html`
   - Example: Add text like "(Tripment - New Change)" at line 7

2. **Commit and push changes**:
   ```bash
   git add .
   git commit -m "Update home page with new change"
   git push
   ```

3. **Monitor the pipeline**:
   - CodePipeline will be triggered automatically
   - Source stage: Pulls code from GitLab
   - Build stage: CodeBuild builds and pushes to ECR
   - Deploy stage: CodeDeploy performs blue/green deployment

4. **Verify deployment**:
   - **Production** (unchanged): `http://<alb-dns>:80`
   - **Test environment** (new changes): `http://<alb-dns>:8080`

5. **Traffic rerouting**:
   - After 5 minutes (configured wait time), pipeline waits for approval
   - Verify changes on port 8080
   - Click **"Reroute traffic"** in CodeDeploy to switch production traffic
   - Old tasks remain running briefly for potential rollback
   - After verification, old tasks are terminated

### Blue/Green Deployment Flow

1. **Blue Environment**: Current production (port 80)
2. **Green Environment**: New deployment (port 8080 for testing)
3. **Testing Phase**: Verify green environment (5 minutes)
4. **Traffic Switch**: Production traffic routes to green
5. **Rollback Option**: Available until old tasks terminated
6. **Termination**: Old blue environment terminated after success

## Clean-up

To avoid ongoing AWS charges:

1. **Delete CodePipeline**:
   - Developer Tools → CodePipeline → Select pipeline → Delete

2. **Delete CodeBuild Project**:
   - Developer Tools → CodeBuild → Select project → Delete

3. **Delete CodeDeploy**:
   - CodeDeploy → Applications → Delete application

4. **Delete ECS Service**:
   - ECS → Clusters → Select cluster → Services → Delete service

5. **Delete ECS Cluster**:
   - ECS → Clusters → Delete cluster

6. **Delete Load Balancer**:
   - EC2 → Load Balancers → Delete load balancer

7. **Delete Target Groups**:
   - EC2 → Target Groups → Delete both target groups

8. **Delete ECR Repository**:
   - ECR → Repositories → Delete repository

9. **Delete RDS Database**:
   - RDS → Databases → Delete (uncheck snapshot option for demo)

10. **Delete IAM Roles**:
    - IAM → Roles → Delete custom roles created

11. **Delete Security Groups**:
    - EC2 → Security Groups → Delete custom security groups

## Key Features

- ✅ **Zero-downtime deployments**: Blue/green strategy ensures service availability
- ✅ **Automated rollback**: Quick revert to previous version if issues detected
- ✅ **Testing before production**: Verify changes on test port before switching traffic
- ✅ **High availability**: Multi-AZ deployment with Aurora replication
- ✅ **Auto-scaling**: ECS handles traffic spikes automatically
- ✅ **Full CI/CD automation**: From code commit to production deployment

## Architecture Benefits

- **Resilience**: Multi-AZ deployment for both compute and database
- **Scalability**: Auto-scaling groups respond to demand
- **Security**: VPC, security groups, and IAM roles for access control
- **Observability**: CloudWatch integration for monitoring
- **Cost Optimization**: Auto-scaling prevents over-provisioning

## Common Issues and Solutions

### Pipeline Fails at Build Stage
- Verify IAM role has ECR push permissions
- Check buildspec.yml syntax
- Ensure Docker is enabled (privileged mode)

### ECS Tasks Not Starting
- Verify task execution role has necessary permissions
- Check ECR image exists and is accessible
- Verify RDS endpoint and credentials in environment variables

### Load Balancer Health Checks Failing
- Ensure security group allows ALB to reach instances
- Verify application is listening on correct port
- Check health check path is valid

### CodeDeploy Deployment Fails
- Verify target groups are correctly configured
- Check appspec.yaml and taskdef.json are valid
- Ensure CodeDeploy role has necessary permissions

## Reference

This workshop is based on the AWS Community Day Workshop by Jones Ndzenyuy.

Original blog post: [AWS Community Day Workshop: Building Your First DevOps Blue/Green Pipeline with ECS](https://dev.to/ndzenyuy/aws-community-day-workshop-building-your-first-devops-bluegreen-pipeline-with-ecs-4o67)

## Additional Resources

- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [AWS CodePipeline Documentation](https://docs.aws.amazon.com/codepipeline/)
- [Blue/Green Deployments with ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-bluegreen.html)
- [AWS CodeDeploy Documentation](https://docs.aws.amazon.com/codedeploy/)

---

**Workshop Author**: Jones Ndzenyuy  
**Last Updated**: November 2024  
**Tags**: #aws #ecs #cicd #devops #bluegreen #codepipeline

