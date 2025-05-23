import docker
from docker.errors import DockerException
from .models import DockerContainer
from users.models import CustomUser
from django.conf import settings
import os

client = docker.from_env()

def create_container(user: CustomUser, image_name: str):
    if client is None:
        return False
        
    try:
        # Pull the image first
        client.images.pull(image_name)
        
        # Create container with resource limits
        container = client.containers.create(
            image=image_name,
            name=f"user_{user.id}_container",
            mem_limit=f"{user.ram_limit}m",
            cpu_shares=int(user.cpu_limit * 1024),
            volumes={
                os.path.join(settings.MEDIA_ROOT, f'User_{user.id}_({user.username})'): {
                    'bind': '/workspace', 
                    'mode': 'rw'
                }
            },
            ports={'80/tcp': user.id + 8000},
            runtime='nvidia' if user.gpu_access else None,
            detach=True
        )
        
        # Save container info to database
        DockerContainer.objects.update_or_create(
            user=user,
            defaults={
                'container_id': container.id,
                'image_name': image_name,
                'status': 'created',
                'port_bindings': {'80_tcp': user.id + 8000}  # Note the underscore
            }
        )
        return True
    except DockerException as e:
        print(f"Docker error: {e}")
        return False
    
def start_container(user):
    if client is None:
        return False
    
    try:
        container = DockerContainer.objects.get(user=user)
        docker_container = client.containers.get(container.container_id)
        docker_container.start()
        container.status = 'running'
        container.save()
        return True
    except (DockerContainer.DoesNotExist, docker.errors.NotFound):
        return False

def stop_container(user):
    if client is None:
        return False
    
    try:
        container = DockerContainer.objects.get(user=user)
        docker_container = client.containers.get(container.container_id)
        docker_container.stop()
        container.status = 'stopped'
        container.save()
        return True
    except (DockerContainer.DoesNotExist, docker.errors.NotFound):
        return False

def delete_container(user):
    if client is None:
        return False
    
    try:
        container = DockerContainer.objects.get(user=user)
        docker_container = client.containers.get(container.container_id)
        docker_container.remove(force=True)
        container.delete()
        return True
    except (DockerContainer.DoesNotExist, docker.errors.NotFound):
        return False

def get_user_container_stats(user):
    """Get statistics for a user's Docker container"""
    if not client:
        return None
    
    try:
        container = DockerContainer.objects.get(user=user)
        docker_container = client.containers.get(container.container_id)
        
        stats = docker_container.stats(stream=False)
        cpu_stats = stats['cpu_stats']
        precpu_stats = stats['precpu_stats']
        
        # Calculate CPU percentage
        cpu_delta = cpu_stats['cpu_usage']['total_usage'] - precpu_stats['cpu_usage']['total_usage']
        system_delta = cpu_stats['system_cpu_usage'] - precpu_stats['system_cpu_usage']
        cpu_percent = (cpu_delta / system_delta) * 100 if system_delta > 0 else 0
        
        return {
            'cpu_percent': round(cpu_percent, 2),
            'memory_usage': stats['memory_stats'].get('usage', 0),
            'memory_limit': stats['memory_stats'].get('limit', 0),
            'memory_percent': (stats['memory_stats'].get('usage', 0) / stats['memory_stats'].get('limit', 1)) * 100,
            'network': stats.get('networks', {}),
            'status': container.status
        }
    except (DockerContainer.DoesNotExist, docker.errors.NotFound):
        return None