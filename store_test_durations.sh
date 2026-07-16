#!/usr/bin/env bash

USE_IPYKERNEL=true pixi run --environment=py313 pytest -vvv --store-durations
