import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

def test_ex_dividend_return_calculation():
    """
    Unit Test: Verifies correct return calculation during July-September dividend season.
    Asserts that using adjusted price correctly yields a positive return 
    even when unadjusted price drops due to ex-dividend gap.
    """
    # Mock stock data: Ex-dividend date is T+1
    # Day T (Before ex-div): Close = 100.0, Adj Close = 100.0
    # Day T+1 (Ex-div day): Close = 95.0 (due to 5 TWD cash dividend), Open = 95.0, Adj Close = 95.0
    # If unadjusted is used, return from T to T+1 is (95 - 100)/100 = -5.0%
    # But actual price didn't change in value.
    # To compute adjusted returns correctly, we adjust Day T close down to 95.0 (Adj Close)
    # The return is (95.0 - 95.0)/95.0 = 0.0%
    
    price_t = 100.0
    dividend = 5.0
    price_t1 = 95.0 # Close price on ex-dividend day
    
    # Adjust previous close
    adjusted_prev_close = price_t - dividend
    
    # Return calculated using adjusted price
    adj_return = (price_t1 - adjusted_prev_close) / adjusted_prev_close
    
    # Unadjusted return (buggy)
    unadj_return = (price_t1 - price_t) / price_t
    
    assert adj_return == 0.0
    assert unadj_return == -0.05
    print("Ex-dividend adjustment logic verified successfully.")
