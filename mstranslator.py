# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import requests
import datetime
import json
try:
    basestring
except NameError:
    basestring = (str, bytes)


MSTRANSLATOR_TIMEOUT = 30


class AccessError(Exception):
    def __init__(self, response):
        self.status_code = response.status_code
        data = response.json()
        super(AccessError, self).__init__(data["message"])


class ArgumentOutOfRangeException(Exception):
    def __init__(self, message):
        self.message = message.replace('ArgumentOutOfRangeException: ', '')
        super(ArgumentOutOfRangeException, self).__init__(self.message)


class TranslateApiException(Exception):
    def __init__(self, message, *args):
        self.message = message.replace('TranslateApiException: ', '')
        super(TranslateApiException, self).__init__(self.message, *args)


class AccessToken(object):
    access_url = "https://api.cognitive.microsoft.com/sts/v1.0/issueToken"
    # Translator API valid for 10 minutes, actually
    expire_delta = datetime.timedelta(minutes=9)

    def __init__(self, subscription_key):
        self.subscription_key = subscription_key
        self._token = None
        self._expdate = None

    def __call__(self, r):
        r.headers['Authorization'] = "Bearer " + self.token
        return r

    def request_token(self):
        headers = {
            'Ocp-Apim-Subscription-Key': self.subscription_key
        }
        resp = requests.post(self.access_url, headers=headers)
        if resp.status_code == 200:
            self._token = resp.text
            self._expdate = datetime.datetime.now() + self.expire_delta
        else:
            raise AccessError(resp)

    @property
    def expired(self):
        return datetime.datetime.now() > self._expdate

    @property
    def token(self):
        if not self._token or self.expired:
            self.request_token()
        return self._token


class Translator(object):
    api_url = "https://api.microsofttranslator.com/v2/ajax.svc/"

    def __init__(self, subscription_key):
        self.auth = AccessToken(subscription_key)

    def make_url(self, action):
        return self.api_url + action

    def make_request(self, action, params=None):
        url = self.make_url(action)
        resp = requests.get(url, auth=self.auth, params=params,
                            timeout=MSTRANSLATOR_TIMEOUT)
        return self.make_response(resp)

    def make_response(self, resp):
        resp.encoding = 'UTF-8-sig'
        data = resp.json()

        if isinstance(data, basestring) and data.startswith("ArgumentOutOfRangeException"):
            raise ArgumentOutOfRangeException(data)

        if isinstance(data, basestring) and data.startswith("TranslateApiException"):
            raise TranslateApiException(data)

        return data

    def _translate(self, action, text_params, lang_from, lang_to, contenttype, category):
        if not lang_to:
            raise ValueError('lang_to parameter is required')
        if contenttype not in ('text/plain', 'text/html'):
            raise ValueError('Invalid contenttype value')

        params = {
            'to': lang_to,
            'contentType': contenttype,
            'category': category,
        }
        if lang_from:
            params['from'] = lang_from
        params.update(text_params)

        return self.make_request(action, params)

    def translate(self, text, lang_from=None, lang_to=None,
                  contenttype='text/plain', category='general'):
        params = {
            'text': text,
        }
        return self._translate('Translate', params, lang_from, lang_to,
                               contenttype, category)

    def translate_array(self, texts=[], lang_from=None, lang_to=None,
                        contenttype='text/plain', category='general'):
        params = {
            'texts': json.dumps(texts),
        }
        return self._translate('TranslateArray', params, lang_from, lang_to,
                               contenttype, category)

    def translate_array2(self, texts=[], lang_from=None, lang_to=None,
                         contenttype='text/plain', category='general'):
        params = {
            'texts': json.dumps(texts),
        }
        return self._translate('TranslateArray2', params, lang_from, lang_to,
                               contenttype, category)

    def get_translations(self, text, lang_from, lang_to, max_n=10, contenttype='text/plain', category='general',
                         url=None, user=None, state=None):
        options = {
            'Category': category,
            'ContentType': contenttype,
        }
        if url:
            options['Uri'] = url
        if user:
            options['User'] = user
        if state:
            options['State'] = state
        params = {
            'text': text,
            'to': lang_to,
            'from': lang_from,
            'maxTranslations': max_n,
            'options': json.dumps(options)
        }
        return self.make_request('GetTranslations', params)

    def break_sentences(self, text, lang):
        if len(text) > 10000:
            raise ValueError('The text maximum length is 10000 characters')
        params = {
            'text': text,
            'language': lang,
        }
        lengths = self.make_request('BreakSentences', params)
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        c = 0
        result = []
        for i in lengths:
            result.append(text[c:c + i])
            c += i
        return result

    def add_translation(self, text_orig, text_trans, lang_from, lang_to, user, rating=1,
                        contenttype='text/plain', category='general', url=None):
        if len(text_orig) > 1000:
            raise ValueError(
                'The original text maximum length is 1000 characters')
        if len(text_trans) > 2000:
            raise ValueError(
                'The translated text maximum length is 1000 characters')
        if contenttype not in ('text/plain', 'text/html'):
            raise ValueError('Invalid contenttype value')
        if not -10 < rating < 10 or not isinstance(rating, int):
            raise ValueError(
                'Raiting must be an integer value between -10 and 10')
        params = {
            'originalText': text_orig,
            'translatedText': text_trans,
            'from': lang_from,
            'to': lang_to,
            'user': user,
            'contentType': contenttype,
            'rating': rating,
            'category': category,
        }
        if url:
            params['uri'] = url
        return self.make_request('AddTranslation', params)

    def get_langs(self, speakable=False):
        action = 'GetLanguagesForSpeak' if speakable else 'GetLanguagesForTranslate'
        return self.make_request(action)

    def get_lang_names(self, langs, lang_to):
        params = {
            'locale': lang_to,
            'languageCodes': json.dumps(langs),
        }
        return self.make_request('GetLanguageNames', params)

    def detect_lang(self, text):
        return self.make_request('Detect', {'text': text})

    def detect_langs(self, texts=[]):
        return self.make_request('DetectArray', {'texts': json.dumps(texts)})

    def speak(self, text, lang, format='audio/wav', best_quality=False):
        if format not in ('audio/wav', 'audio/mp3'):
            raise ValueError('Invalid format value')
        params = {
            'text': text,
            'language': lang,
            'format': format,
            'options': 'MaxQuality' if best_quality else 'MinSize',
        }
        return self.make_request('Speak', params)

    def speak_to_file(self, file, *args, **kwargs):
        resp = requests.get(self.speak(*args, **kwargs))
        if isinstance(file, basestring):
            with open(file, 'wb'):
                file.write(resp.content)
        elif hasattr(file, 'write'):
            file.write(resp.content)
        else:
            raise ValueError('Expected filepath or a file-like object')
