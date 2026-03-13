# Ruby test file
module MathUtils
  class Calculator
    attr_reader :result

    def initialize
      @result = 0
    end

    def add(value)
      @result += value
      self
    end

    def multiply(value)
      @result *= value
      self
    end

    def self.create
      new
    end
  end
end
