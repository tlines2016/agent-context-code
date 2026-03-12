# Elixir test file
defmodule Calculator do
  @moduledoc "A simple calculator"

  def add(a, b), do: a + b

  def subtract(a, b), do: a - b

  defp internal_helper(x), do: x * 2
end

defprotocol Printable do
  def to_string(data)
end
