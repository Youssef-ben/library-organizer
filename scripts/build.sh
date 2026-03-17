#!/bin/bash

source ./scripts/initialize.sh

echo "Building the application..."
echo "--------------------------------"
echo "Building the application..."
pyinstaller library-organizer.spec

echo "--------------------------------"
echo "Application built successfully."
