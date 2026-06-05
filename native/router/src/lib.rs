use std::borrow::Cow;
use std::collections::HashMap;

use matchit::Router as MatchitRouter;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule, PyTuple};

enum Converter {
    Str,
    Int,
}

struct ParamSpec {
    name: String,
    converter: Converter,
}

struct RouteEntry {
    route: Py<PyAny>,
    params: Vec<ParamSpec>,
}

struct AllowedEntry {
    methods: Vec<String>,
    params: Vec<ParamSpec>,
}

enum ConvertedParams {
    Empty,
    Dict(Py<PyDict>),
}

type RouteMatch = Option<(Py<PyAny>, Option<Py<PyDict>>)>;

#[pyclass(module = "quater._router")]
struct RouteMatcher {
    routes: HashMap<String, MatchitRouter<RouteEntry>>,
    allowed: MatchitRouter<AllowedEntry>,
}

#[pymethods]
impl RouteMatcher {
    #[new]
    fn new() -> Self {
        Self {
            routes: HashMap::new(),
            allowed: MatchitRouter::new(),
        }
    }

    fn insert_route(
        &mut self,
        method: &str,
        path: &str,
        route: Py<PyAny>,
        params: Vec<(String, String)>,
    ) -> PyResult<()> {
        let entry = RouteEntry {
            route,
            params: parse_param_specs(params)?,
        };

        self.routes
            .entry(method.to_owned())
            .or_default()
            .insert(path, entry)
            .map_err(route_insert_error)
    }

    fn insert_allowed(
        &mut self,
        path: &str,
        methods: Vec<String>,
        params: Vec<(String, String)>,
    ) -> PyResult<()> {
        let entry = AllowedEntry {
            methods,
            params: parse_param_specs(params)?,
        };

        self.allowed.insert(path, entry).map_err(route_insert_error)
    }

    fn match_route(&self, py: Python<'_>, method: &str, path: &str) -> PyResult<RouteMatch> {
        let Some(router) = self.routes.get(method) else {
            return Ok(None);
        };

        let path = normalize_request_path(path);
        let Ok(matched) = router.at(path.as_ref()) else {
            return Ok(None);
        };

        let Some(params) = convert_params(py, &matched.value.params, &matched.params)? else {
            return Ok(None);
        };

        let params = match params {
            ConvertedParams::Empty => None,
            ConvertedParams::Dict(dict) => Some(dict),
        };

        Ok(Some((matched.value.route.clone_ref(py), params)))
    }

    fn allowed_methods(&self, py: Python<'_>, path: &str) -> PyResult<Option<Py<PyTuple>>> {
        let path = normalize_request_path(path);
        let Ok(matched) = self.allowed.at(path.as_ref()) else {
            return Ok(None);
        };

        if convert_params(py, &matched.value.params, &matched.params)?.is_none() {
            return Ok(None);
        }

        let methods = PyTuple::new(py, matched.value.methods.iter())?;
        Ok(Some(methods.unbind()))
    }
}

fn parse_param_specs(raw_specs: Vec<(String, String)>) -> PyResult<Vec<ParamSpec>> {
    let mut specs = Vec::with_capacity(raw_specs.len());
    for (name, converter_name) in raw_specs {
        let converter = match converter_name.as_str() {
            "str" => Converter::Str,
            "int" => Converter::Int,
            _ => {
                return Err(PyValueError::new_err(format!(
                    "unsupported path converter: {converter_name}"
                )));
            }
        };
        specs.push(ParamSpec { name, converter });
    }
    Ok(specs)
}

fn convert_params(
    py: Python<'_>,
    specs: &[ParamSpec],
    params: &matchit::Params<'_, '_>,
) -> PyResult<Option<ConvertedParams>> {
    if specs.is_empty() {
        return Ok(Some(ConvertedParams::Empty));
    }

    let dict = PyDict::new(py);
    for spec in specs {
        let Some(raw_value) = params.get(spec.name.as_str()) else {
            return Ok(None);
        };

        match spec.converter {
            Converter::Str => dict.set_item(spec.name.as_str(), raw_value)?,
            Converter::Int => {
                if !set_int_param(py, &dict, spec.name.as_str(), raw_value)? {
                    return Ok(None);
                }
            }
        }
    }

    Ok(Some(ConvertedParams::Dict(dict.unbind())))
}

fn set_int_param(
    py: Python<'_>,
    dict: &Bound<'_, PyDict>,
    name: &str,
    raw_value: &str,
) -> PyResult<bool> {
    // The `:int` converter only matches one canonical URL form: a non-empty run
    // of ASCII digits, `[0-9]+`. This rejects signs (`+5`, `-7`), digit grouping
    // (`1_000`), surrounding whitespace, and non-ASCII digits (`٣`, `１`) that a
    // bare `int()` would otherwise accept, so distinct URLs cannot alias the
    // same id.
    if !is_canonical_ascii_int(raw_value) {
        return Ok(false);
    }

    if let Ok(value) = raw_value.parse::<i64>() {
        dict.set_item(name, value)?;
        return Ok(true);
    }

    // The value is all ASCII digits but exceeds i64; fall back to Python's
    // arbitrary-precision int. This cannot reintroduce non-canonical forms
    // because `raw_value` is already validated as `[0-9]+`.
    let builtins = PyModule::import(py, "builtins")?;
    let int_type = builtins.getattr("int")?;
    let value = int_type.call1((raw_value,))?;
    dict.set_item(name, value)?;
    Ok(true)
}

fn is_canonical_ascii_int(raw_value: &str) -> bool {
    !raw_value.is_empty() && raw_value.bytes().all(|byte| byte.is_ascii_digit())
}

fn normalize_request_path(path: &str) -> Cow<'_, str> {
    if !needs_path_normalization(path) {
        return Cow::Borrowed(path);
    }

    let mut normalized = String::with_capacity(path.len() + 1);
    for segment in path.split('/').filter(|segment| !segment.is_empty()) {
        normalized.push('/');
        normalized.push_str(segment);
    }

    if normalized.is_empty() {
        Cow::Borrowed("/")
    } else {
        Cow::Owned(normalized)
    }
}

fn needs_path_normalization(path: &str) -> bool {
    if path.is_empty() || !path.starts_with('/') {
        return true;
    }
    if path.len() > 1 && path.ends_with('/') {
        return true;
    }

    path.as_bytes().windows(2).any(|window| window == b"//")
}

fn route_insert_error(error: matchit::InsertError) -> PyErr {
    PyValueError::new_err(format!("route insert failed: {error}"))
}

#[pymodule(name = "_router")]
fn quater_router(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<RouteMatcher>()?;
    Ok(())
}
