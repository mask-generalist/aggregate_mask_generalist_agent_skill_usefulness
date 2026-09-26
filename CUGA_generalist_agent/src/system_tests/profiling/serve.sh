#!/bin/bash

# Simple HTTP server for viewing profiling experiments
# Serves the experiments directory on port 8080

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENTS_DIR="$SCRIPT_DIR/experiments"
PORT=8080

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port|-p)
            PORT="$2"
            shift 2
            ;;
        --open|-o)
            OPEN_BROWSER=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -p, --port PORT    Port to serve on (default: 8080)"
            echo "  -o, --open         Open browser automatically"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                 # Start server on port 8080"
            echo "  $0 --port 3000     # Start server on port 3000"
            echo "  $0 --open          # Start and open browser"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if port is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "Port $PORT is already in use."
    echo -n "Kill existing process and continue? (y/n) "
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        lsof -ti:$PORT | xargs kill -9 2>/dev/null
        echo "Killed existing process on port $PORT"
        sleep 1
    else
        echo "Exiting. Choose a different port with --port"
        exit 1
    fi
fi

echo "=========================================="
echo "  CUGA Profiling Results Viewer"
echo "=========================================="
echo ""
echo "Starting HTTP server..."
echo "  Directory: $EXPERIMENTS_DIR"
echo "  Port: $PORT"
echo "  URL: http://localhost:$PORT/comparison.html"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Open browser if requested
if [ "$OPEN_BROWSER" = true ]; then
    echo "Opening browser..."
    sleep 1
    
    if command -v open > /dev/null; then
        open "http://localhost:$PORT/comparison.html"
    elif command -v xdg-open > /dev/null; then
        xdg-open "http://localhost:$PORT/comparison.html"
    else
        echo "Could not open browser automatically"
        echo "Please visit: http://localhost:$PORT/comparison.html"
    fi
fi

# Start server
cd "$EXPERIMENTS_DIR"
uv run python -m http.server $PORT
