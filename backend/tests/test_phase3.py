import os
import shutil
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.services import AuthenticationService
from app.tools.filesystem.security import FileSystemJail

# Override the jail path for testing specifically so we don't mess up main workspace
TEST_WORKSPACE = "/tmp/mcp_test_workspace"

@pytest.fixture(autouse=True)
def setup_test_workspace():
    # Recreate pristine test workspace directory
    shutil.rmtree(TEST_WORKSPACE, ignore_errors=True)
    os.makedirs(TEST_WORKSPACE, exist_ok=True)
    yield
    shutil.rmtree(TEST_WORKSPACE, ignore_errors=True)

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_headers():
    token = AuthenticationService.create_token(
        user_id="test_user",
        email="test@example.com",
        scopes=["mcp:execute"]
    )
    return {"Authorization": f"Bearer {token}"}

def test_filesystem_jail_traversal_prevention():
    jail = FileSystemJail(base_path=TEST_WORKSPACE)
    
    # 1. Safe path resolving inside the sandbox
    safe_path = jail.secure_resolve("notes.txt")
    assert safe_path.name == "notes.txt"
    assert safe_path.parent == Path(TEST_WORKSPACE).resolve()

    # 2. Block direct traversal attempt
    with pytest.raises(PermissionError, match="Access denied: Path escapes sandbox boundary"):
        jail.secure_resolve("../../../etc/passwd")

    # 3. Block absolute paths out of boundary
    with pytest.raises(PermissionError, match="Access denied: Path escapes sandbox boundary"):
        jail.secure_resolve("/etc/passwd")

def test_filesystem_jail_deny_lists():
    jail = FileSystemJail(base_path=TEST_WORKSPACE)
    
    # 1. Block prohibited extension (.env)
    with pytest.raises(PermissionError, match="Access denied: Restricted file type"):
        jail.secure_resolve("config.env")
        
    # 2. Block prohibited directory (.git)
    with pytest.raises(PermissionError, match="Access denied: Restricted directory"):
        jail.secure_resolve(".git/config")

def test_filesystem_jail_size_limit():
    jail = FileSystemJail(base_path=TEST_WORKSPACE)
    
    # 1. Create a large file
    filepath = Path(TEST_WORKSPACE) / "large.txt"
    with open(filepath, "wb") as f:
        # Write 501 KB (Limit is 500 KB)
        f.write(b"A" * (1024 * 501))
        
    # 2. Assert exception is raised
    with pytest.raises(ValueError, match="File too large"):
        jail.check_size(filepath)

def test_e2e_write_and_read_file(client, auth_headers):
    # Ensure handlers read/write from test workspace
    from app.tools.filesystem.handlers import jail as active_jail
    active_jail.base_path = Path(TEST_WORKSPACE).resolve()
    
    # 1. Securely write to a safe file
    write_payload = {
        "tool_name": "fs.write_file",
        "arguments": {
            "file_path": "hello.txt",
            "content": "Hello, sandboxed world!"
        }
    }
    write_response = client.post("/api/v1/mcp/execute", json=write_payload, headers=auth_headers)
    assert write_response.status_code == 200
    assert write_response.json()["success"] is True
    assert "Successfully wrote" in write_response.json()["data"]

    # 2. Securely read the file back
    read_payload = {
        "tool_name": "fs.read_file",
        "arguments": {
            "file_path": "hello.txt"
        }
    }
    read_response = client.post("/api/v1/mcp/execute", json=read_payload, headers=auth_headers)
    assert read_response.status_code == 200
    assert read_response.json()["success"] is True
    assert read_response.json()["data"] == "Hello, sandboxed world!"

def test_e2e_list_directory(client, auth_headers):
    # Ensure handlers list from test workspace
    from app.tools.filesystem.handlers import jail as active_jail
    active_jail.base_path = Path(TEST_WORKSPACE).resolve()
    
    # Create test items
    os.makedirs(os.path.join(TEST_WORKSPACE, "subfolder"), exist_ok=True)
    with open(os.path.join(TEST_WORKSPACE, "item.txt"), "w") as f:
        f.write("text content")

    payload = {
        "tool_name": "fs.list_dir",
        "arguments": {
            "directory_path": "."
        }
    }
    response = client.post("/api/v1/mcp/execute", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    entries = response.json()["data"]
    assert len(entries) == 2
    
    names = [e["name"] for e in entries]
    assert "subfolder" in names
    assert "item.txt" in names

def test_e2e_blocked_traversal_attack(client, auth_headers):
    from app.tools.filesystem.handlers import jail as active_jail
    active_jail.base_path = Path(TEST_WORKSPACE).resolve()
    
    payload = {
        "tool_name": "fs.read_file",
        "arguments": {
            "file_path": "../../../etc/passwd"
        }
    }
    response = client.post("/api/v1/mcp/execute", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
    # The handler catches the exception and returns it inside a clean payload string
    assert "Access denied: Path escapes sandbox boundary." in response.json()["data"]
