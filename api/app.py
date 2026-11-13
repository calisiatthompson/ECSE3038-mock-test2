from fastapi.responses import JSONResponse
from paho.mqtt import publish
import os
import secrets

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

app = FastAPI()

# MongoDB connection
client = MongoClient(os.environ["MONGODB_URI"])
db = client["mock_test2"]
devices = db["devices"]
readings = db["readings"]
alarms = db["alarms"]

MQTT_BROKER = "135.232.203.144"
MQTT_NAME = os.environ["MQTT_NAME"]

# Prevent duplicate MAC addresses
devices.create_index("mac", unique=True)


class Device(BaseModel):
    mac: str
    room: str

class Reading(BaseModel):
    mac: str
    temp: float = Field(ge=-40, le=80)

class Alarm(BaseModel):
    max_temp: float


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


@app.post("/readings", status_code=201)
def create_reading(
    reading: Reading,
    x_api_key: str | None = Header(default=None)
):

    # Check if an API key was provided
    if x_api_key is None:
        raise HTTPException(
            status_code=401,
            detail="API key required"
        )

    # Find the device using the API key
    device = devices.find_one({"api_key": x_api_key})

    if device is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    # Check if the key belongs to this MAC
    if device["mac"] != reading.mac:
        raise HTTPException(
            status_code=403,
            detail="Key belongs to another device"
        )

    # Create the reading
    new_reading = reading.model_dump()

    # Add the server timestamp
    new_reading["time"] = datetime.now(timezone.utc)

    # Save the reading in MongoDB
    readings.insert_one(new_reading.copy())

    return new_reading


@app.get("/readings")
def get_readings(
    mac: str | None = None,
    since: datetime | None = None
):

    query = {}

    if mac is not None:
        query["mac"] = mac

    if since is not None:
        query["time"] = {"$gte": since}

    return list(
        readings.find(query, {"_id": 0})
        .sort("time", -1)
    )


@app.put("/alarm/{mac}")
def set_alarm(mac: str, alarm: Alarm):

    # Check if the device exists
    if devices.find_one({"mac": mac}) is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    # Create alarm document
    new_alarm = {
        "mac": mac,
        "max_temp": alarm.max_temp
    }

    # Create or update alarm in MongoDB
    result = alarms.replace_one(
        {"mac": mac},
        new_alarm.copy(),
        upsert=True
    )

    # Publish the limit to MQTT
    topic = f"ecse3038/{MQTT_NAME}/alarm/max"

    publish.single(
        topic,
        payload=str(alarm.max_temp),
        hostname=MQTT_BROKER,
        port=1883,
        retain=True
    )

    # Return 201 if newly created
    if result.upserted_id is not None:
        return JSONResponse(
            status_code=201,
            content=new_alarm
        )

    return new_alarm

