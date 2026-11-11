def test_register_and_login(client):
    r=client.post("/api/v1/auth/register",json={"email":"donor@example.test","password":"long-enough-password"})
    assert r.status_code == 201
    r=client.post("/api/v1/auth/login",json={"email":"donor@example.test","password":"long-enough-password"})
    assert r.status_code == 200 and r.json["data"]["access_token"]

def test_registration_cannot_assign_role(client):
    r=client.post("/api/v1/auth/register",json={"email":"x@example.test","password":"long-enough-password","role":"admin"})
    assert r.status_code == 201
    assert r.json["data"]["role"] == "donor"

def test_wrong_password_is_unauthorized_without_account_disclosure(client):
    client.post("/api/v1/auth/register",json={"email":"private@example.test","password":"long-enough-password"})
    response=client.post("/api/v1/auth/login",json={"email":"private@example.test","password":"wrong-password"})
    assert response.status_code == 401
    assert response.json["error"]["code"] == "INVALID_CREDENTIALS"
