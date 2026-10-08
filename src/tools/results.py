"""Results evaluation and export tools for COMSOL MCP Server."""

from .errors import error_record

from typing import Optional, Union, Sequence
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from .session import session_manager


def register_results_tools(mcp: FastMCP) -> None:
    """Register results tools with the MCP server."""
    
    @mcp.tool()
    def results_evaluate(
        expression: Union[str, Sequence[str]],
        unit: Optional[str] = None,
        dataset: Optional[str] = None,
        inner: Optional[Union[int, str, Sequence[int]]] = None,
        outer: Optional[Union[int, Sequence[int]]] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Evaluate an expression on a solution dataset.
        
        Args:
            expression: Expression(s) to evaluate, e.g., "es.normE" or ["x", "y", "es.normE"]
            unit: Desired unit for result, e.g., "V/m", "pF"
            dataset: Dataset name (default: uses default dataset)
            inner: For time-dependent solutions: index, 'first', 'last', or list of indices
            outer: For parametric sweeps: index or list of indices
            model_name: Model name (default: current model)
        
        Returns:
            Evaluated values as lists, or error message
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            result = model.evaluate(
                expression,
                unit=unit,
                dataset=dataset,
                inner=inner,
                outer=outer,
            )
            
            from .evaluation import encode
            return {"success": True, "expression": expression, "unit": unit,
                    "dataset": dataset, **encode(result)}
        except Exception as e:
            return {**error_record(e, 'results_evaluate'), "success": False, "error": f"Failed to evaluate: {str(e)}"}
    
    @mcp.tool()
    def results_global_evaluate(
        expression: str,
        unit: Optional[str] = None,
        dataset: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Evaluate a global expression, preserving every solution value and complex part.
        
        Common global expressions include:
        - Integration: "intop1(T)" where intop1 is an integration operator
        - Maximum: "maxop1(T)" 
        - Derived values: "2*es.intWe/U^2" for capacitance
        
        Args:
            expression: Global expression to evaluate
            unit: Desired unit for result
            dataset: Dataset name
            model_name: Model name (default: current model)
        
        Returns:
            Numerical scalar or array, with explicit real/imag for complex results
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            result = model.evaluate(expression, unit=unit, dataset=dataset)
            
            from .evaluation import encode
            return {"success": True, "expression": expression, "unit": unit,
                    "dataset": dataset, **encode(result)}
        except Exception as e:
            return {**error_record(e, 'results_global_evaluate'), "success": False, "error": f"Failed to evaluate global expression: {str(e)}"}
    
    @mcp.tool()
    def results_inner_values(
        dataset: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get inner solution indices and values (time steps in time-dependent study).
        
        Args:
            dataset: Dataset name (default: default dataset)
            model_name: Model name (default: current model)
        
        Returns:
            Arrays of indices and corresponding values (e.g., time values)
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            indices, values = model.inner(dataset)
            
            return {
                "success": True,
                "dataset": dataset,
                "indices": indices.tolist() if hasattr(indices, 'tolist') else list(indices),
                "values": values.tolist() if hasattr(values, 'tolist') else list(values),
                "count": len(values),
            }
        except Exception as e:
            return {**error_record(e, 'results_inner_values'), "success": False, "error": f"Failed to get inner values: {str(e)}"}
    
    @mcp.tool()
    def results_outer_values(
        dataset: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get outer solution indices and values (parameter values in parametric sweep).
        
        Args:
            dataset: Dataset name (default: default dataset)
            model_name: Model name (default: current model)
        
        Returns:
            Arrays of indices and corresponding parameter values
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            indices, values = model.outer(dataset)
            
            return {
                "success": True,
                "dataset": dataset,
                "indices": indices.tolist() if hasattr(indices, 'tolist') else list(indices),
                "values": values.tolist() if hasattr(values, 'tolist') else list(values),
                "count": len(values),
            }
        except Exception as e:
            return {**error_record(e, 'results_outer_values'), "success": False, "error": f"Failed to get outer values: {str(e)}"}
    
    @mcp.tool()
    def results_export_data(
        node_name: Optional[str] = None,
        file_path: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Export data from an export node.
        
        Args:
            node_name: Export node name (default: run all exports)
            file_path: Output file path (overrides node setting)
            model_name: Model name (default: current model)
        
        Returns:
            Export confirmation with file path
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            model.export(node_name, file_path)
            
            return {
                "success": True,
                "node": node_name,
                "file": file_path,
                "message": f"Export completed: {node_name or 'all exports'}",
            }
        except Exception as e:
            return {**error_record(e, 'results_export_data'), "success": False, "error": f"Failed to export data: {str(e)}"}
    
    @mcp.tool()
    def results_export_image(
        node_name: Optional[str] = None,
        file_path: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Export a plot as an image.
        
        Args:
            node_name: Plot export node name
            file_path: Output image path (e.g., "results.png", "field.png")
            model_name: Model name (default: current model)
        
        Returns:
            Export confirmation with file path
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            model.export(node_name, file_path)
            
            return {
                "success": True,
                "node": node_name,
                "file": file_path,
                "message": f"Image exported to: {file_path}",
            }
        except Exception as e:
            return {**error_record(e, 'results_export_image'), "success": False, "error": f"Failed to export image: {str(e)}"}
    
    @mcp.tool()
    def results_exports_list(model_name: Optional[str] = None) -> dict:
        """
        List all export nodes defined in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of export node names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            exports = model.exports()
            return {
                "success": True,
                "exports": exports,
                "count": len(exports),
            }
        except Exception as e:
            return {**error_record(e, 'results_exports_list'), "success": False, "error": f"Failed to list exports: {str(e)}"}
    
    @mcp.tool()
    def results_plots_list(model_name: Optional[str] = None) -> dict:
        """
        List all plot nodes defined in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of plot node names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            plots = model.plots()
            return {
                "success": True,
                "plots": plots,
                "count": len(plots),
            }
        except Exception as e:
            return {**error_record(e, 'results_plots_list'), "success": False, "error": f"Failed to list plots: {str(e)}"}
