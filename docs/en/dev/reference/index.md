---
description: Reference for every public symbol exported from the quater package, with exact names, signatures, and defaults.
---

# Reference

This reference documents every public symbol exported from `quater`.

## Prerequisites

Use this section after reading [Quickstart](/en/dev/quickstart) and
[Public API](/en/dev/api). The reference tells you exact names and defaults;
the guides show how to design an app.

## Public Imports

```python
from quater import Quater, Request, JSONResponse, Resource
```

Public symbols:

| Area | Symbols |
| --- | --- |
| Application | [`Quater`](./application#symbol-quater), [`RouteGroup`](./application#symbol-routegroup), [`AppConfig`](./application#symbol-appconfig), [`CORSConfig`](./application#symbol-corsconfig), [`__version__`](./application#symbol-version) |
| Parameters | [`Path`](./parameters#symbol-path), [`Query`](./parameters#symbol-query), [`Body`](./parameters#symbol-body), [`Form`](./parameters#symbol-form), [`File`](./parameters#symbol-file), [`Header`](./parameters#symbol-header), [`Cookie`](./parameters#symbol-cookie) |
| Request | [`Request`](./request#symbol-request), [`State`](./request#symbol-state), [`FormData`](./request#symbol-formdata), [`UploadFile`](./request#symbol-uploadfile) |
| Resources | [`Resource`](./resources#symbol-resource) |
| Responses | [`Response`](./responses#symbol-response), [`JSONResponse`](./responses#symbol-jsonresponse), [`TextResponse`](./responses#symbol-textresponse), [`HTMLResponse`](./responses#symbol-htmlresponse), [`BytesResponse`](./responses#symbol-bytesresponse), [`StreamResponse`](./responses#symbol-streamresponse), [`RedirectResponse`](./responses#symbol-redirectresponse), [`EmptyResponse`](./responses#symbol-emptyresponse) |
| Auth | [`AuthConfig`](./auth#symbol-authconfig), [`AuthContext`](./auth#symbol-authcontext), [`ApprovalRequest`](./auth#symbol-approvalrequest), [`ActionApproval`](./auth#symbol-actionapproval), [`HTTPError`](./auth#symbol-httperror), [`ImproperlyConfigured`](./auth#symbol-improperlyconfigured), [`SignedCookieSigner`](./auth#symbol-signedcookiesigner) |
| Observability | [`AccessLogEvent`](./observability#symbol-accesslogevent), [`AccessLogHook`](./observability#symbol-accessloghook), [`ToolAuditEvent`](./observability#symbol-toolauditevent) |
| Testing | [`TestClient`](./testing#symbol-testclient), [`MCPTestClient`](./testing#symbol-mcptestclient), [`TestResponse`](./testing#symbol-testresponse) |

## Pages

- [Application](./application): app construction, route groups, CORS, and
  server-facing objects.
- [Parameters](./parameters): request binding markers.
- [Request](./request): request object, state, headers, query, cookies, and
  context.
- [Resources](./resources): scoped injection.
- [Responses](./responses): automatic return conversion and explicit responses.
- [Auth and Security](./auth): auth hooks, approval hooks, errors, and signed
  cookies.
- [Observability](./observability): access-log and MCP audit events.
- [Testing](./testing): in-process HTTP and MCP test clients.

## What Can Go Wrong

If a symbol does not appear here, do not treat it as public API. If application
code needs an internal import, treat that as a design question before depending
on it.

## Also See

- [Stability](/en/dev/stability): version pinning and upgrade expectations.
- [Public API](/en/dev/api): human explanation before the reference.
- [Quickstart](/en/dev/quickstart): first working app.
