import json
from datetime import datetime, timedelta

from functools import wraps
import requests
import jwt
from django.conf import settings
from rest_framework.decorators import api_view, parser_classes
from rest_framework.response import Response
from rest_framework.parsers import JSONParser

from jwt import DecodeError, ExpiredSignature

from api.models import User
from api.serializers import GoogleAuthSerializer
from api.errors import AuthenticationError, AuthorizationError, \
    InvalidRequestData


def create_token(user):
    payload = {
        'sub': str(user.id),
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + timedelta(days=14)
    }
    token = jwt.encode(payload, settings.SECRET_KEY)
    return token.decode('unicode_escape')


def parse_token(request):
    try:
        token = request.META.get('HTTP_AUTHORIZATION').split()[1]
    except IndexError:
        raise InvalidRequestData('Incomplete Authorization header.')

    return jwt.decode(token, settings.SECRET_KEY)


def login_required(f):
    @wraps(f)
    def decorated_function(request, *args, **kwargs):
        if not request.META.get('HTTP_AUTHORIZATION'):
            raise InvalidRequestData('Missing Authorization header.')

        try:
            payload = parse_token(request)
        except DecodeError:
            raise AuthorizationError('Token is invalid.')
        except ExpiredSignature:
            raise AuthorizationError('Token has expired.')

        user = User.objects.get(id=payload['sub'])
        return f(request, user, *args, **kwargs)

    return decorated_function


@api_view(('POST',))
@parser_classes((JSONParser,))
def google(request):
    """API authentication using Google OAuth2"""
    serializer = GoogleAuthSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    access_token_url = 'https://accounts.google.com/o/oauth2/token'
    userinfo_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
    payload = {
        'client_id': serializer.validated_data['clientId'],
        'redirect_uri': serializer.validated_data['redirectUri'],
        'client_secret': settings.GOOGLE_SECRET,
        'code': serializer.validated_data['code'],
        'grant_type': 'authorization_code'
    }

    # Step 1. Exchange authorization code for access token.
    r = requests.post(access_token_url, data=payload)
    token = json.loads(r.text)
    try:
        headers = {'Authorization': 'Bearer {0}'.format(token['access_token'])}
    except KeyError:
        raise AuthenticationError(token['error'])

    # Step 2. Retrieve information about the current user.
    r = requests.get(userinfo_url, headers=headers)
    profile = json.loads(r.text)
    user = User.objects(google=profile['id']).first()
    if user:
        token = create_token(user)
        return Response({'token': token})

    u = User(email=profile['email'], google=profile['id'],
             display_name=profile['name'])
    u.save()
    token = create_token(u)
    return Response({'token': token})
