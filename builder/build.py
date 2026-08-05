import subprocess, os, shutil

REGISTRY = "localhost:5000"

def build_and_push(repo_url: str, app_name: str, version: int) -> str:
    build_dir = f"/tmp/build-{app_name}"
    image_tag = f"{REGISTRY}/{app_name}:v{version}"

    print(f"[builder] Cloning {repo_url}...")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)

    subprocess.run(["/usr/bin/git", "clone", repo_url, build_dir], check=True)

    if not os.path.exists(f"{build_dir}/Dockerfile"):
        raise Exception(f"No Dockerfile found in {repo_url}")

    print(f"[builder] Building image {image_tag}...")
    result = subprocess.run(
        ["/usr/bin/docker", "build", "-t", image_tag, build_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise Exception(f"Docker build failed:\n{result.stderr}")

    print(f"[builder] Pushing to registry...")
    push_result = subprocess.run(
        ["/usr/bin/docker", "push", image_tag],
        capture_output=True, text=True
    )
    if push_result.returncode != 0:
        raise Exception(f"Docker push failed:\n{push_result.stderr}")

    shutil.rmtree(build_dir, ignore_errors=True)
    print(f"[builder] Done: {image_tag}")
    return image_tag
