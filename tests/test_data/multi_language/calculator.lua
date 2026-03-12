-- Lua test file
local function greet(name)
    print("Hello " .. name)
end

function Calculator:new()
    local calc = {}
    setmetatable(calc, self)
    self.__index = self
    calc.result = 0
    return calc
end

function Calculator:add(value)
    self.result = self.result + value
    return self
end

local sum = function(a, b) return a + b end
