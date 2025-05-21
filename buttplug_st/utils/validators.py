from typing import Optional, Any, Dict
from ..core.exceptions import ValidationError

def validate_float_range(
    value: Any,
    min_val: float = 0.0,
    max_val: float = 1.0,
    param_name: str = "value"
) -> float:
    """Validate that a value is a float within the specified range"""
    try:
        float_val = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Parameter '{param_name}' must be a number")
    
    if float_val < min_val or float_val > max_val:
        raise ValidationError(
            f"Parameter '{param_name}' must be between {min_val} and {max_val}, got {float_val}"
        )
    
    return float_val

def extract_query_params(query_args: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract and validate query parameters with defaults"""
    if defaults is None:
        defaults = {}
    
    result = {}
    
    for key, default_value in defaults.items():
        if key in query_args:
            result[key] = query_args[key]
        else:
            result[key] = default_value
            
    return result 