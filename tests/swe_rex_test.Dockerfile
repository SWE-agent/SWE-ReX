FROM python:3.12-slim

COPY . /swe-rex

WORKDIR /swe-rex

RUN pip install -e .