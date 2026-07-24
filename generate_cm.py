import sys
import yaml

with open("MLOPS-Full-Data-Pipeline/app.py", "r") as f:
    app_py_content = f.read()

cm = {
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "fraud-app-py",
        "namespace": "oppe2-app"
    },
    "data": {
        "app.py": app_py_content
    }
}

with open("flagship-gitops/manifests/mlops/app-configmap.yaml", "w") as f:
    yaml.dump(cm, f)

print("ConfigMap updated successfully.")
