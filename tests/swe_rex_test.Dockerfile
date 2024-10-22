FROM python:3.11-slim

COPY . /swe-rex

WORKDIR /swe-rex

RUN pip install -e .