#!/bin/bash
# Script to run service_now_agent-1 using the virtual environment

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Navigate to the project directory
cd "$SCRIPT_DIR"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment 'venv' not found."
    echo "Please create it first: python3 -m venv venv"
    exit 1
fi

echo "Starting service_now_agent-1..."
# Use the python executable from the virtual environment directly
./venv/bin/python3 main.py
