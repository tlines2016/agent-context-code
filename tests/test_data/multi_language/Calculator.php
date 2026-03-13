<?php
namespace App;

class Calculator {
    private float $result;

    public function __construct() {
        $this->result = 0;
    }

    public function add(float $value): self {
        $this->result += $value;
        return $this;
    }

    public static function create(): self {
        return new self();
    }
}

interface MathOperations {
    public function calculate(float $a, float $b): float;
}

trait Logging {
    public function log(string $msg): void {
        echo $msg;
    }
}

function standalone_add(float $a, float $b): float {
    return $a + $b;
}
