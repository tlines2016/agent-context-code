import Foundation

class Calculator {
    var result: Double = 0.0

    init() {
        result = 0.0
    }

    func add(_ value: Double) -> Calculator {
        result += value
        return self
    }

    static func create() -> Calculator {
        return Calculator()
    }
}

struct Point {
    var x: Double
    var y: Double
}

protocol MathOperations {
    func calculate(_ a: Double, _ b: Double) -> Double
}

enum Operation {
    case add, subtract, multiply, divide
}

extension Calculator: MathOperations {
    func calculate(_ a: Double, _ b: Double) -> Double {
        return a + b
    }
}

func standalone() -> Int {
    return 42
}
