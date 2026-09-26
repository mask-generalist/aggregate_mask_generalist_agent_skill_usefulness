#!/bin/bash

# Colors for output formatting
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Make sure logs directory exists
mkdir -p logs

# Function to show usage instructions
show_usage() {
  echo -e "${BLUE}Usage:${NC}"
  echo -e "  $0 ${GREEN}start${NC} [service_name]     - Start all services or a specific one"
  echo -e "  $0 ${YELLOW}stop${NC} [service_name]      - Stop all services or a specific one"
  echo -e "  $0 ${RED}restart${NC} [service_name]   - Restart all services or a specific one"
  echo -e "  $0 ${BLUE}status${NC}                - Show status of all services"
  echo -e "  $0 ${BLUE}logs${NC} [service_name]      - Show logs for all services or a specific one"
  echo -e "  $0 ${BLUE}monit${NC}                 - Launch PM2 monitoring dashboard"
  echo
  echo -e "${BLUE}Available services:${NC}"
  echo -e "  - environment-server   (Environment server on port 8005)"
  echo -e "  - api-server           (API server on port 9000)"
  echo -e "  - cuga-agent           (Cuga Agent server)"
  echo -e "  - mcp-registry         (MCP registry server)"
}

# Check if PM2 is installed
check_pm2() {
  if ! command -v pm2 &> /dev/null; then
    echo -e "${RED}PM2 is not installed. Please install it first:${NC}"
    echo "npm install -g pm2"
    exit 1
  fi
}

# Start services
start_services() {
  if [ -z "$1" ]; then
    echo -e "${GREEN}Starting all services...${NC}"
    pm2 start ecosystem.config.json
  else
    echo -e "${GREEN}Starting service: $1${NC}"
    pm2 start ecosystem.config.json --only "$1"
  fi
}

# Stop services
stop_services() {
  if [ -z "$1" ]; then
    echo -e "${YELLOW}Stopping all services...${NC}"
    pm2 stop ecosystem.config.json
  else
    echo -e "${YELLOW}Stopping service: $1${NC}"
    pm2 stop "$1"
  fi
}

# Restart services
restart_services() {
  if [ -z "$1" ]; then
    echo -e "${RED}Restarting all services...${NC}"
    pm2 restart ecosystem.config.json
  else
    echo -e "${RED}Restarting service: $1${NC}"
    pm2 restart "$1"
  fi
}

# Show service status
show_status() {
  echo -e "${BLUE}Service status:${NC}"
  pm2 list
}

# Show logs
show_logs() {
  if [ -z "$1" ]; then
    echo -e "${BLUE}Showing logs for all services:${NC}"
    pm2 logs
  else
    echo -e "${BLUE}Showing logs for service: $1${NC}"
    pm2 logs "$1"
  fi
}

# Show monitoring dashboard
show_monit() {
  echo -e "${BLUE}Launching PM2 monitoring dashboard...${NC}"
  pm2 monit
}

# Main function
main() {
  check_pm2

  case "$1" in
    start)
      start_services "$2"
      ;;
    stop)
      stop_services "$2"
      ;;
    restart)
      restart_services "$2"
      ;;
    status)
      show_status
      ;;
    logs)
      show_logs "$2"
      ;;
    monit)
      show_monit
      ;;
    *)
      show_usage
      ;;
  esac
}

# Run the main function
main "$@"