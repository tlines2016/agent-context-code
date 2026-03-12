// Scala test file
package demo

trait MathOperations {
  def calculate(a: Int, b: Int): Int
}

class Calculator(val name: String) extends MathOperations {
  def calculate(a: Int, b: Int): Int = a + b

  def add(a: Int, b: Int): Int = a + b

  val version: String = "1.0"
}

object Calculator {
  def create(): Calculator = new Calculator("default")
}

case class Point(x: Double, y: Double)

sealed trait Shape
