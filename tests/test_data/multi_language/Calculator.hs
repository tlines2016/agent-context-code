-- Haskell test file
module Calculator where

add :: Int -> Int -> Int
add a b = a + b

data Shape = Circle Double | Rectangle Double Double

class Describable a where
  describe :: a -> String

instance Describable Shape where
  describe (Circle r) = "Circle with radius " ++ show r
  describe (Rectangle w h) = "Rectangle " ++ show w ++ "x" ++ show h

type Name = String

newtype Wrapper a = Wrapper { unwrap :: a }
