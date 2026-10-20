def test_health_is_dynamic_and_utc(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "HEALTHY"
    assert response.json()["current_time"].endswith("Z")


def test_webhook_query_duplicate_and_conflict(client):
    payload = {
        "transaction_id": "txn_api_1",
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": 1500,
        "currency": "INR",
    }
    accepted = client.post("/v1/webhooks/transactions", json=payload)
    assert accepted.status_code == 202
    assert accepted.json()["duplicate"] is False

    queried = client.get("/v1/transactions/txn_api_1")
    assert queried.status_code == 200
    assert queried.json()["status"] == "PROCESSING"
    assert queried.json()["processed_at"] is None
    assert queried.json()["amount"] == "1500.0000"

    duplicate = client.post("/v1/webhooks/transactions", json=payload)
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True

    conflict = client.post(
        "/v1/webhooks/transactions",
        json={**payload, "amount": 1501},
    )
    assert conflict.status_code == 409


def test_unknown_and_invalid_requests(client):
    assert client.get("/v1/transactions/does_not_exist").status_code == 404
    invalid = client.post("/v1/webhooks/transactions", json={"transaction_id": "x"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_validation_details_are_json_serializable(client):
    response = client.post(
        "/v1/webhooks/transactions",
        json={
            "transaction_id": "txn_api_precision",
            "source_account": "acc_user_789",
            "destination_account": "acc_merchant_456",
            "amount": "1.12345",
            "currency": "INR",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["type"] == "value_error"
