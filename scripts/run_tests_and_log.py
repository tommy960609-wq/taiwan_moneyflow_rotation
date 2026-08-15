import subprocess
import os
import sys
import hashlib

def get_dir_hash(path):
    hash_func = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        for names in sorted(files):
            file_path = os.path.join(root, names)
            if '.pytest_cache' in file_path or '__pycache__' in file_path or '.git' in file_path:
                continue
            try:
                with open(file_path, 'rb') as f:
                    while chunk := f.read(8192):
                        hash_func.update(chunk)
            except:
                pass
    return hash_func.hexdigest()

def run_tests_and_log():
    base_dir = "C:/Workspace_CN/taiwan_moneyflow_rotation"
    log_path = os.path.join(base_dir, "loop/evidence/test_logs/pytest_run_log.txt")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    cmd = [
        "Quant-Agent/.venv/Scripts/python.exe", 
        "-m", "pytest", 
        "taiwan_moneyflow_rotation/tests", 
        "-v"
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd="C:/Workspace_CN", capture_output=True)
    
    # Decode bytes safely
    stdout_str = res.stdout.decode("utf-8", errors="ignore")
    stderr_str = res.stderr.decode("utf-8", errors="ignore")
    
    # Calculate checksum hash of src/, config/, scripts/, and tests/ (B5 compliance)
    src_hash = get_dir_hash(os.path.join(base_dir, "src"))
    config_hash = get_dir_hash(os.path.join(base_dir, "config"))
    scripts_hash = get_dir_hash(os.path.join(base_dir, "scripts"))
    tests_hash = get_dir_hash(os.path.join(base_dir, "tests"))
    
    combined_raw = f"{src_hash}{config_hash}{scripts_hash}{tests_hash}"
    combined_hash = hashlib.sha256(combined_raw.encode("utf-8")).hexdigest()
    
    meta_header = (
        "============================================================\n"
        "TEST RUN EVIDENCE RECEIPT (Milestone 1)\n"
        "============================================================\n"
        f"Command: python -m pytest taiwan_moneyflow_rotation/tests -v\n"
        f"Exit Code: {res.returncode}\n"
        f"Combined Code & Config Hash: {combined_hash}\n"
        "Coverage: N/A (Coverage metrics explicitly not required for M1)\n"
        "============================================================\n\n"
    )
    
    combined_output = f"{meta_header}Stdout:\n{stdout_str}\n\nStderr:\n{stderr_str}"
    
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(combined_output)
        
    print(f"Pytest output logged successfully with checksum to {log_path}")
    print(stdout_str)
    
    sys.exit(res.returncode)

if __name__ == "__main__":
    run_tests_and_log()
