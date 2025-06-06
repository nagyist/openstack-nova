# Copyright 2013 IBM Corp.
# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import functools
import typing as ty

import microversion_parse
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import strutils
import webob

from nova.api.openstack import api_version_request
from nova.api import wsgi
from nova import exception
from nova import i18n
from nova.i18n import _
from nova import version


LOG = logging.getLogger(__name__)

_SUPPORTED_CONTENT_TYPES = (
    'application/json',
    'application/vnd.openstack.compute+json',
)

# These are typically automatically created by routes as either defaults
# collection or member methods.
_ROUTES_METHODS = [
    'create',
    'delete',
    'show',
    'update',
]

_METHODS_WITH_BODY = [
    'POST',
    'PUT',
]

# The default api version request if none is requested in the headers
# Note(cyeoh): This only applies for the v2.1 API once microversions
# support is fully merged. It does not affect the V2 API.
DEFAULT_API_VERSION = "2.1"

# Names of headers used by clients to request a specific version
# of the REST API
API_VERSION_REQUEST_HEADER = 'OpenStack-API-Version'
LEGACY_API_VERSION_REQUEST_HEADER = 'X-OpenStack-Nova-API-Version'


ENV_LEGACY_V2 = 'openstack.legacy_v2'


def get_supported_content_types():
    return _SUPPORTED_CONTENT_TYPES


class Request(wsgi.Request):
    """Add some OpenStack API-specific logic to the base webob.Request."""

    def __init__(self, *args, **kwargs):
        super(Request, self).__init__(*args, **kwargs)
        if not hasattr(self, 'api_version_request'):
            self.api_version_request = api_version_request.APIVersionRequest()

    def best_match_content_type(self):
        """Determine the requested response content-type."""
        if 'nova.best_content_type' not in self.environ:
            # Calculate the best MIME type
            content_type = None

            # Check URL path suffix
            parts = self.path.rsplit('.', 1)
            if len(parts) > 1:
                possible_type = 'application/' + parts[1]
                if possible_type in get_supported_content_types():
                    content_type = possible_type

            if not content_type:
                best_matches = self.accept.acceptable_offers(
                    get_supported_content_types())
                if best_matches:
                    content_type = best_matches[0][0]

            self.environ['nova.best_content_type'] = (content_type or
                                                      'application/json')

        return self.environ['nova.best_content_type']

    def get_content_type(self):
        """Determine content type of the request body.

        Does not do any body introspection, only checks header

        """
        if "Content-Type" not in self.headers:
            return None

        content_type = self.content_type

        # NOTE(markmc): text/plain is the default for eventlet and
        # other webservers which use mimetools.Message.gettype()
        # whereas twisted defaults to ''.
        if not content_type or content_type == 'text/plain':
            return None

        if content_type not in get_supported_content_types():
            raise exception.InvalidContentType(content_type=content_type)

        return content_type

    def best_match_language(self):
        """Determine the best available language for the request.

        :returns: the best language match or None if the 'Accept-Language'
                  header was not available in the request.
        """
        if not self.accept_language:
            return None

        # NOTE(takashin): To decide the default behavior, 'default' is
        # preferred over 'default_tag' because that is return as it is when
        # no match. This is also little tricky that 'default' value cannot be
        # None. At least one of default_tag or default must be supplied as
        # an argument to the method, to define the defaulting behavior.
        # So passing a sentinel value to return None from this function.
        best_match = self.accept_language.lookup(
            i18n.get_available_languages(), default='fake_LANG')

        if best_match == 'fake_LANG':
            best_match = None
        return best_match

    def set_api_version_request(self):
        """Set API version request based on the request header information."""
        hdr_string = microversion_parse.get_version(
            self.headers, service_type='compute',
            legacy_headers=[LEGACY_API_VERSION_REQUEST_HEADER])

        if hdr_string is None:
            self.api_version_request = api_version_request.APIVersionRequest(
                api_version_request.DEFAULT_API_VERSION)
        elif hdr_string == 'latest':
            # 'latest' is a special keyword which is equivalent to
            # requesting the maximum version of the API supported
            self.api_version_request = api_version_request.max_api_version()
        else:
            self.api_version_request = api_version_request.APIVersionRequest(
                hdr_string)

            # Check that the version requested is within the global
            # minimum/maximum of supported API versions
            if not self.api_version_request.matches(
                    api_version_request.min_api_version(),
                    api_version_request.max_api_version()):
                raise exception.InvalidGlobalAPIVersion(
                    req_ver=self.api_version_request.get_string(),
                    min_ver=api_version_request.min_api_version().get_string(),
                    max_ver=api_version_request.max_api_version().get_string())

    def set_legacy_v2(self):
        self.environ[ENV_LEGACY_V2] = True

    def is_legacy_v2(self):
        return self.environ.get(ENV_LEGACY_V2, False)


class ActionDispatcher(object):
    """Maps method name to local methods through action name."""

    def dispatch(self, *args, **kwargs):
        """Find and call local method."""
        action = kwargs.pop('action', 'default')
        action_method = getattr(self, str(action), self.default)
        return action_method(*args, **kwargs)

    def default(self, data):
        raise NotImplementedError()


class JSONDeserializer(ActionDispatcher):

    def _from_json(self, datastring):
        try:
            return jsonutils.loads(datastring)
        except ValueError:
            msg = _("cannot understand JSON")
            raise exception.MalformedRequestBody(reason=msg)

    def deserialize(self, datastring, action='default'):
        return self.dispatch(datastring, action=action)

    def default(self, datastring):
        return {'body': self._from_json(datastring)}


class JSONDictSerializer(ActionDispatcher):
    """Default JSON request body serialization."""

    def serialize(self, data, action='default'):
        return self.dispatch(data, action=action)

    def default(self, data):
        return str(jsonutils.dumps(data))


class WSGICodes:
    """A microversion-aware WSGI code decorator.

    Allow definition and retrieval of WSGI return codes on a microversion-aware
    basis.
    """

    def __init__(self) -> None:
        self._codes: list[tuple[int, ty.Optional[str], ty.Optional[str]]] = []

    def add_code(
        self, code: tuple[int, ty.Optional[str], ty.Optional[str]]
    ) -> None:
        self._codes.append(code)

    def __call__(self, req: Request) -> int:
        ver = req.api_version_request

        for code, min_version, max_version in self._codes:
            min_ver = api_version_request.APIVersionRequest(min_version)
            max_ver = api_version_request.APIVersionRequest(max_version)
            if ver.matches(min_ver, max_ver):
                return code

        LOG.error("Unknown return code in API method")
        msg = _("Unknown return code in API method")
        raise webob.exc.HTTPInternalServerError(explanation=msg)


def response(
    code: int,
    min_version: ty.Optional[str] = None,
    max_version: ty.Optional[str] = None,
):
    """Attaches response code to a method.

    This decorator associates a response code with a method.  Note
    that the function attributes are directly manipulated; the method
    is not wrapped.
    """

    def decorator(func):
        if not hasattr(func, 'wsgi_codes'):
            func.wsgi_codes = WSGICodes()
        func.wsgi_codes.add_code((code, min_version, max_version))
        return func
    return decorator


class ResponseObject(object):
    """Bundles a response object

    Object that app methods may return in order to allow its response
    to be modified by extensions in the code. Its use is optional (and
    should only be used if you really know what you are doing).
    """

    def __init__(self, obj, code=None, headers=None):
        """Builds a response object."""

        self.obj = obj
        self._default_code = 200
        self._code = code
        self._headers = headers or {}
        self.serializer = JSONDictSerializer()

    def __getitem__(self, key):
        """Retrieves a header with the given name."""

        return self._headers[key.lower()]

    def __setitem__(self, key, value):
        """Sets a header with the given name to the given value."""

        self._headers[key.lower()] = value

    def __delitem__(self, key):
        """Deletes the header with the given name."""

        del self._headers[key.lower()]

    def serialize(self, request, content_type):
        """Serializes the wrapped object.

        Utility method for serializing the wrapped object.  Returns a
        webob.Response object.

        Header values are set to the appropriate Python type and
        encoding demanded by PEP 3333: whatever the native str type is.
        """

        serializer = self.serializer

        body = None
        if self.obj is not None:
            body = serializer.serialize(self.obj)
        response = webob.Response(body=body)
        response.status_int = self.code
        for hdr, val in self._headers.items():
            # In Py3.X Headers must be a str that was first safely
            # encoded to UTF-8 (to catch any bad encodings) and then
            # decoded back to a native str.
            response.headers[hdr] = encodeutils.safe_decode(
                    encodeutils.safe_encode(val))
        # Deal with content_type
        if not isinstance(content_type, str):
            content_type = str(content_type)
        # In Py3.X Headers must be a str.
        response.headers['Content-Type'] = encodeutils.safe_decode(
                encodeutils.safe_encode(content_type))
        return response

    @property
    def code(self):
        """Retrieve the response status."""

        return self._code or self._default_code

    @property
    def headers(self):
        """Retrieve the headers."""

        return self._headers.copy()


def action_peek(body):
    """Determine action to invoke.

    This looks inside the json body and fetches out the action method
    name.
    """

    try:
        decoded = jsonutils.loads(body)
    except ValueError:
        msg = _("cannot understand JSON")
        raise exception.MalformedRequestBody(reason=msg)

    # Make sure there's exactly one key...
    if len(decoded) != 1:
        msg = _("too many body keys")
        raise exception.MalformedRequestBody(reason=msg)

    # Return the action name
    return list(decoded.keys())[0]


class ResourceExceptionHandler(object):
    """Context manager to handle Resource exceptions.

    Used when processing exceptions generated by API implementation
    methods.  Converts most exceptions to Fault
    exceptions, with the appropriate logging.
    """

    def __enter__(self):
        return None

    def __exit__(self, ex_type, ex_value, ex_traceback):
        if not ex_value:
            return True

        if isinstance(ex_value, exception.Forbidden):
            raise Fault(webob.exc.HTTPForbidden(
                    explanation=ex_value.format_message()))
        elif isinstance(ex_value, exception.VersionNotFoundForAPIMethod):
            raise
        elif isinstance(ex_value, exception.Invalid):
            raise Fault(exception.ConvertedException(
                    code=ex_value.code,
                    explanation=ex_value.format_message()))
        elif isinstance(ex_value, TypeError):
            exc_info = (ex_type, ex_value, ex_traceback)
            LOG.error('Exception handling resource: %s', ex_value,
                      exc_info=exc_info)
            raise Fault(webob.exc.HTTPBadRequest())
        elif isinstance(ex_value, Fault):
            LOG.info("Fault thrown: %s", ex_value)
            raise ex_value
        elif isinstance(ex_value, webob.exc.HTTPException):
            LOG.info("HTTP exception thrown: %s", ex_value)
            raise Fault(ex_value)

        # We didn't handle the exception
        return False


class Resource(wsgi.Application):
    """WSGI app that handles (de)serialization and controller dispatch.

    WSGI app that reads routing information supplied by RoutesMiddleware
    and calls the requested action method upon its controller.  All
    controller action methods must accept a 'req' argument, which is the
    incoming wsgi.Request. If the operation is a PUT or POST, the controller
    method must also accept a 'body' argument (the deserialized request body).
    They may raise a webob.exc exception or return a dict, which will be
    serialized by requested content type.

    Exceptions derived from webob.exc.HTTPException will be automatically
    wrapped in Fault() to provide API friendly error responses.

    """
    support_api_request_version = True

    def __init__(self, controller):
        """:param controller: object that implement methods created by routes
                              lib
        """
        self.controller = controller
        self.sub_controllers = []

        self.default_serializers = dict(json=JSONDictSerializer)

        # Copy over the actions dictionary
        self.wsgi_actions = {}
        if controller:
            self.register_actions(controller)

    def register_actions(self, controller):
        """Registers controller actions with this resource."""

        actions = getattr(controller, 'wsgi_actions', {})
        for key, method_name in actions.items():
            self.wsgi_actions[key] = getattr(controller, method_name)

    def register_subcontroller_actions(self, sub_controller):
        """Registers sub-controller actions with this resource."""
        self.sub_controllers.append(sub_controller)
        actions = getattr(sub_controller, 'wsgi_actions', {})
        for key, method_name in actions.items():
            self.wsgi_actions[key] = getattr(sub_controller, method_name)

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""

        # NOTE(Vek): Check for get_action_args() override in the
        # controller
        if hasattr(self.controller, 'get_action_args'):
            return self.controller.get_action_args(request_environment)

        try:
            args = request_environment['wsgiorg.routing_args'][1].copy()
        except (KeyError, IndexError, AttributeError):
            return {}

        try:
            del args['controller']
        except KeyError:
            pass

        try:
            del args['format']
        except KeyError:
            pass

        return args

    def get_body(self, request):
        content_type = request.get_content_type()

        return content_type, request.body

    def deserialize(self, body):
        return JSONDeserializer().deserialize(body)

    def _should_have_body(self, request):
        return request.method in _METHODS_WITH_BODY

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, request):
        """WSGI method that controls (de)serialization and method dispatch."""

        if self.support_api_request_version:
            # Set the version of the API requested based on the header
            try:
                request.set_api_version_request()
            except exception.InvalidAPIVersionString as e:
                return Fault(webob.exc.HTTPBadRequest(
                    explanation=e.format_message()))
            except exception.InvalidGlobalAPIVersion as e:
                return Fault(webob.exc.HTTPNotAcceptable(
                    explanation=e.format_message()))

        # Identify the action, its arguments, and the requested
        # content type
        action_args = self.get_action_args(request.environ)
        action = action_args.pop('action', None)

        # NOTE(sdague): we filter out InvalidContentTypes early so we
        # know everything is good from here on out.
        try:
            content_type, body = self.get_body(request)
            accept = request.best_match_content_type()
        except exception.InvalidContentType:
            msg = _("Unsupported Content-Type")
            return Fault(webob.exc.HTTPUnsupportedMediaType(explanation=msg))

        # NOTE(Vek): Splitting the function up this way allows for
        #            auditing by external tools that wrap the existing
        #            function.  If we try to audit __call__(), we can
        #            run into troubles due to the @webob.dec.wsgify()
        #            decorator.
        return self._process_stack(request, action, action_args,
                               content_type, body, accept)

    def _process_stack(self, request, action, action_args,
                       content_type, body, accept):
        """Implement the processing stack."""

        # Get the implementing method
        try:
            meth = self.get_method(request, action,
                                   content_type, body)
        except (AttributeError, TypeError):
            return Fault(webob.exc.HTTPNotFound())
        except KeyError as ex:
            msg = _("There is no such action: %s") % ex.args[0]
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))
        except exception.MalformedRequestBody:
            msg = _("Malformed request body")
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))

        if body:
            msg = _("Action: '%(action)s', calling method: %(meth)s, body: "
                    "%(body)s") % {'action': action,
                                   'body': str(body, 'utf-8'),
                                   'meth': str(meth)}
            LOG.debug(strutils.mask_password(msg))
        else:
            LOG.debug("Calling method '%(meth)s'",
                      {'meth': str(meth)})

        # Now, deserialize the request body...
        try:
            contents = self._get_request_content(body, request)
        except exception.MalformedRequestBody:
            msg = _("Malformed request body")
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))

        # Update the action args
        action_args.update(contents)

        project_id = action_args.pop("project_id", None)
        context = request.environ.get('nova.context')
        if (context and project_id and (project_id != context.project_id)):
            msg = _("Malformed request URL: URL's project_id '%(project_id)s'"
                    " doesn't match Context's project_id"
                    " '%(context_project_id)s'") % \
                    {'project_id': project_id,
                     'context_project_id': context.project_id}
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))

        response = None
        try:
            with ResourceExceptionHandler():
                action_result = self.dispatch(meth, request, action_args)
        except Fault as ex:
            response = ex

        if not response:
            # No exceptions; convert action_result into a
            # ResponseObject
            resp_obj = None
            if type(action_result) is dict or action_result is None:
                resp_obj = ResponseObject(action_result)
            elif isinstance(action_result, ResponseObject):
                resp_obj = action_result
            else:
                response = action_result

            # Run post-processing extensions
            if resp_obj:
                # Do a preserialize to set up the response object
                if hasattr(meth, 'wsgi_codes'):
                    resp_obj._default_code = meth.wsgi_codes(request)

            if resp_obj and not response:
                response = resp_obj.serialize(request, accept)

        if hasattr(response, 'headers'):
            for hdr, val in list(response.headers.items()):
                if not isinstance(val, str):
                    val = str(val)
                # In Py3.X Headers must be a string
                response.headers[hdr] = encodeutils.safe_decode(
                        encodeutils.safe_encode(val))

            if not request.api_version_request.is_null():
                response.headers[API_VERSION_REQUEST_HEADER] = \
                    'compute ' + request.api_version_request.get_string()
                response.headers[LEGACY_API_VERSION_REQUEST_HEADER] = \
                    request.api_version_request.get_string()
                response.headers.add('Vary', API_VERSION_REQUEST_HEADER)
                response.headers.add('Vary', LEGACY_API_VERSION_REQUEST_HEADER)

        return response

    def _get_request_content(self, body, request):
        contents = {}
        if self._should_have_body(request):
            # allow empty body with PUT and POST
            if request.content_length == 0 or request.content_length is None:
                contents = {'body': None}
            else:
                contents = self.deserialize(body)
        return contents

    def get_method(self, request, action, content_type, body):
        meth = self._get_method(request,
                                action,
                                content_type,
                                body)
        return meth

    def _get_method(self, request, action, content_type, body):
        """Look up the action-specific method."""
        # Look up the method
        try:
            if not self.controller:
                meth = getattr(self, action)
            else:
                meth = getattr(self.controller, action)
            return meth
        except AttributeError:
            if (not self.wsgi_actions or
                    action not in _ROUTES_METHODS + ['action']):
                # Propagate the error
                raise
        if action == 'action':
            action_name = action_peek(body)
        else:
            action_name = action

        # Look up the action method
        return (self.wsgi_actions[action_name])

    def dispatch(self, method, request, action_args):
        """Dispatch a call to the action-specific method."""

        try:
            return method(req=request, **action_args)
        except exception.VersionNotFoundForAPIMethod:
            # We deliberately don't return any message information
            # about the exception to the user so it looks as if
            # the method is simply not implemented.
            return Fault(webob.exc.HTTPNotFound())


def action(name):
    """Mark a function as an action.

    The given name will be taken as the action key in the body.

    This is also overloaded to allow extensions to provide
    non-extending definitions of create and delete operations.
    """

    def decorator(func):
        func.wsgi_action = name
        return func
    return decorator


def removed(version: str, reason: str):
    """Mark a function as removed.

    The given reason will be stored as an attribute of the function.
    """
    def decorator(func):
        func.removed = True
        func.removed_version = reason
        func.removed_reason = reason
        return func
    return decorator


def api_version(
    min_version: ty.Optional[str] = None,
    max_version: ty.Optional[str] = None,
):
    """Mark an API as supporting lower and upper version bounds.

    :param min_version: A string of two numerals. X.Y indicating the minimum
        version of the JSON-Schema to validate against.
    :param max_version: A string of two numerals. X.Y indicating the maximum
        version of the JSON-Schema against to.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            min_ver = api_version_request.APIVersionRequest(min_version)
            max_ver = api_version_request.APIVersionRequest(max_version)

            # The request object is always the second argument.
            # However numerous unittests pass in the request object
            # via kwargs instead so we handle that as well.
            # TODO(cyeoh): cleanup unittests so we don't have to
            # to do this
            if 'req' in kwargs:
                ver = kwargs['req'].api_version_request
            else:
                ver = args[1].api_version_request

            if not ver.matches(min_ver, max_ver):
                raise exception.VersionNotFoundForAPIMethod(version=ver)

            return f(*args, **kwargs)

        wrapped.min_version = min_version
        wrapped.max_version = max_version

        return wrapped

    return decorator


def expected_errors(
    errors: ty.Union[int, tuple[int, ...]],
    min_version: ty.Optional[str] = None,
    max_version: ty.Optional[str] = None,
):
    """Decorator for v2.1 API methods which specifies expected exceptions.

    Specify which exceptions may occur when an API method is called. If an
    unexpected exception occurs then return a 500 instead and ask the user
    of the API to file a bug report.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            min_ver = api_version_request.APIVersionRequest(min_version)
            max_ver = api_version_request.APIVersionRequest(max_version)

            # The request object is always the second argument.
            # However numerous unittests pass in the request object
            # via kwargs instead so we handle that as well.
            # TODO(cyeoh): cleanup unittests so we don't have to
            # to do this
            if 'req' in kwargs:
                ver = kwargs['req'].api_version_request
            else:
                ver = args[1].api_version_request

            try:
                return f(*args, **kwargs)
            except Exception as exc:
                # if this instance of the decorator is intended for other
                # versions, let the exception bubble up as-is
                if not ver.matches(min_ver, max_ver):
                    raise

                if isinstance(exc, webob.exc.WSGIHTTPException):
                    if isinstance(errors, int):
                        t_errors = (errors,)
                    else:
                        t_errors = errors
                    if exc.code in t_errors:
                        raise
                elif isinstance(exc, exception.Forbidden):
                    # Note(cyeoh): Special case to handle
                    # Forbidden exceptions so every
                    # extension method does not need to wrap authorize
                    # calls. ResourceExceptionHandler silently
                    # converts NotAuthorized to HTTPForbidden
                    raise
                elif isinstance(exc, exception.NotSupported):
                    # Note(gmann): Special case to handle
                    # NotSupported exceptions. We want to raise 400 BadRequest
                    # for the NotSupported exception which is basically used
                    # to raise for not supported features. Converting it here
                    # will avoid converting every NotSupported inherited
                    # exception in API controller.
                    raise webob.exc.HTTPBadRequest(
                            explanation=exc.format_message())
                elif isinstance(exc, exception.ValidationError):
                    # Note(oomichi): Handle a validation error, which
                    # happens due to invalid API parameters, as an
                    # expected error.
                    raise
                elif isinstance(exc, exception.Unauthorized):
                    # Handle an authorized exception, will be
                    # automatically converted to a HTTP 401, clients
                    # like python-novaclient handle this error to
                    # generate new token and do another attempt.
                    raise

                LOG.exception("Unexpected exception in API method")
                msg = _("Unexpected API Error. "
                        "{support}\n{exc}").format(
                            support=version.support_string(),
                            exc=type(exc))
                raise webob.exc.HTTPInternalServerError(explanation=msg)

        return wrapped

    return decorator


class ControllerMetaclass(type):
    """Controller metaclass.

    This metaclass automates the task of assembling a dictionary
    mapping action keys to method names.
    """

    def __new__(mcs, name, bases, cls_dict):
        """Adds the wsgi_actions dictionary to the class."""
        # Find all actions
        actions = {}

        # start with wsgi actions from base classes
        for base in bases:
            actions.update(getattr(base, 'wsgi_actions', {}))

        for key, value in cls_dict.items():
            if not callable(value):
                continue

            if getattr(value, 'wsgi_action', None):
                actions[value.wsgi_action] = key

        # Add the actions to the class dict
        cls_dict['wsgi_actions'] = actions
        return super(ControllerMetaclass, mcs).__new__(mcs, name, bases,
                                                       cls_dict)


class Controller(metaclass=ControllerMetaclass):
    """Default controller."""

    _view_builder_class = None

    def __init__(self):
        """Initialize controller with a view builder instance."""
        if self._view_builder_class:
            self._view_builder = self._view_builder_class()
        else:
            self._view_builder = None

    @staticmethod
    def is_valid_body(body, entity_name):
        if not (body and entity_name in body):
            return False

        def is_dict(d):
            try:
                d.get(None)
                return True
            except AttributeError:
                return False

        return is_dict(body[entity_name])


class Fault(webob.exc.HTTPException):
    """Wrap webob.exc.HTTPException to provide API friendly response."""

    _fault_names = {
            400: "badRequest",
            401: "unauthorized",
            403: "forbidden",
            404: "itemNotFound",
            405: "badMethod",
            409: "conflictingRequest",
            413: "overLimit",
            415: "badMediaType",
            429: "overLimit",
            501: "notImplemented",
            503: "serviceUnavailable"}

    def __init__(self, exception):
        """Create a Fault for the given webob.exc.exception."""
        self.wrapped_exc = exception
        for key, value in list(self.wrapped_exc.headers.items()):
            self.wrapped_exc.headers[key] = str(value)
        self.status_int = exception.status_int

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, req):
        """Generate a WSGI response based on the exception passed to ctor."""

        user_locale = req.best_match_language()
        # Replace the body with fault details.
        code = self.wrapped_exc.status_int
        fault_name = self._fault_names.get(code, "computeFault")
        explanation = self.wrapped_exc.explanation
        LOG.debug("Returning %(code)s to user: %(explanation)s",
                  {'code': code, 'explanation': explanation})

        explanation = i18n.translate(explanation, user_locale)
        fault_data = {
            fault_name: {
                'code': code,
                'message': explanation}}
        if code == 413 or code == 429:
            retry = self.wrapped_exc.headers.get('Retry-After', None)
            if retry:
                fault_data[fault_name]['retryAfter'] = retry

        if not req.api_version_request.is_null():
            self.wrapped_exc.headers[API_VERSION_REQUEST_HEADER] = \
                'compute ' + req.api_version_request.get_string()
            self.wrapped_exc.headers[LEGACY_API_VERSION_REQUEST_HEADER] = \
                req.api_version_request.get_string()
            self.wrapped_exc.headers.add('Vary', API_VERSION_REQUEST_HEADER)
            self.wrapped_exc.headers.add('Vary',
                                         LEGACY_API_VERSION_REQUEST_HEADER)

        self.wrapped_exc.content_type = 'application/json'
        self.wrapped_exc.charset = 'UTF-8'
        self.wrapped_exc.text = JSONDictSerializer().serialize(fault_data)

        return self.wrapped_exc

    def __str__(self):
        return self.wrapped_exc.__str__()
