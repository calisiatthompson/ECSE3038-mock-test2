import os
import secrets

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# MongoDB connection
client = MongoClient(os.environ["MONGODB_URI"])
db = client["mock_test2"]
devices = db["devices"]

# Prevent duplicate MAC addresses
devices.create_index("mac", unique=True)


class Device(BaseModel):
    mac: str
    room: str


@app.post("/devices", status_code=201)
def create_device(device: Device):

    existing = devices.find_one({"mac": device.mac})

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Device already exists"
        )

    new_device = device.model_dump()

    new_device["api_key"] = secrets.token_urlsafe(16)

    devices.insert_one(new_device.copy())

    return new_device


@app.get("/devices")
def get_devices():

    return list(
        devices.find({}, {"_id": 0, "api_key": 0})
    )
