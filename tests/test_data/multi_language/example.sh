#!/bin/bash

# A greeting function
greet() {
    echo "Hello $1"
}

# Setup function with local variables
function setup {
    local dir=$1
    mkdir -p "$dir"
    echo "Setup complete in $dir"
}

MY_VAR="hello"
