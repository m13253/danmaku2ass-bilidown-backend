#!/usr/bin/env python3

import concurrent.futures
import datetime
import functools
import io
import time

import curl  # https://github.com/m13253/pycurl-python3

import danmaku2ass  # https://github.com/m13253/danmaku2ass

import tornado.gen
import tornado.httpclient
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web


class MainHandler(tornado.web.RequestHandler):

    USER_AGENT = 'BiliDown.tv Danmaku2ASS Tornado/1.0 (sb@loli.con.sh) ; BiliDown.tv Bilibili Node.js API/0.2.0 (zyu@zhuogu.net)'
    COOKIE_VERIFIER = '/cookie_verify'
    MAX_THREADS = 8
    ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(MAX_THREADS)

    @tornado.gen.coroutine
    @tornado.web.asynchronous
    def get(self):
        if not self.verify_rate():
            return
        if not (yield self.verify_cookie()):
            return
        # Parse arguments
        try:
            url = self.get_argument('url')
            width = int(self.get_argument('w'))
            if width <= 0:
                raise ValueError
            height = int(self.get_argument('h'))
            if not (0 < height <= 65535):
                raise ValueError
            reserve_blank = 0
            try:
                reserve_blank = int(self.get_argument('p'))
                if reserve_blank < 0:
                    raise ValueError
            except tornado.web.MissingArgumentError:
                pass
            font_face = 'SimHei'
            try:
                font_face = self.get_argument('fn')
            except tornado.web.MissingArgumentError:
                pass
            font_size = 25
            try:
                font_size = float(self.get_argument('fs'))
                if font_size <= 0:
                    raise ValueError
            except tornado.web.MissingArgumentError:
                pass
            text_opacity = 1.0
            try:
                text_opacity = float(self.get_argument('a'))
                if not (0 <= text_opacity <= 1):
                    raise ValueError
            except tornado.web.MissingArgumentError:
                pass
            comment_duration = 5.0
            try:
                comment_duration = float(self.get_argument('l'))
            except tornado.web.MissingArgumentError:
                pass
            is_reduce_comments = False
            try:
                self.get_argument('r')
                is_reduce_comments = True
            except tornado.web.MissingArgumentError:
                pass
            x_forwarded_for = None
            try:
                x_forwarded_for = self.request.remote_ip
            except tornado.web.MissingArgumentError:
                pass
            output_filename = 'comments.ass'
            try:
                output_filename = self.get_argument('o')
            except tornado.web.MissingArgumentError:
                pass
        except (ValueError, tornado.web.MissingArgumentError):
            self.set_status(400)
            self.set_header('Content-Type', 'text/html; charset=utf-8')
            self.render('specification.html')
            return
        # Open a local file (socket) or download it
        if url.startswith('file:///'):
            fi = url[7:]
        else:
            try:
                fi = io.StringIO((yield self.fetch_input(url)))
            except Exception as e:
                return self.print_error(e)
        # Go and convert it
        fo = io.StringIO()
        try:
            self.ThreadPoolExecutor.submit(
                danmaku2ass.Danmaku2ASS, [fi], fo, width, height, reserve_blank, font_face, font_size, text_opacity, comment_duration, is_reduce_comments
            ).add_done_callback(
                lambda future: tornado.ioloop.IOLoop.instance().add_callback(functools.partial(self.danmaku2ass_finished, fo, output_filename, future))
            )
        except Exception as e:
            return self.print_error(e)

    def danmaku2ass_finished(self, fo, output_filename, future):
        e = future.exception()
        if e:
            return self.print_error(e)
        fo.seek(0)
        self.set_header('Content-Type', 'application/octet-stream')
        self.set_header('Content-Disposition', 'attachment; filename="%s"' % output_filename)
        self.set_header('Cache-Control', 'public, max-age=60')
        self.set_header('Expires', datetime.datetime.utcnow()+datetime.timedelta(minutes=1))
        self.write(''.encode('utf-8-sig'))
        self.finish(fo.read())

    def print_error(self, e, status=500):
        try:
            self.set_status(status)
        except Exception:
            self.set_status(500)
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.render('error.html', e=e)

    @tornado.gen.coroutine
    def fetch_input(self, url):
        '''Download comment file from the Internet'''
        if not url.startswith('http://comment.bilibili.tv/') and not url.startswith('http://comment.bilibili.cn/') and not url.startswith('http://www.bilidown.tv/'):
            raise ValueError('specified URL violates domain restriction')
        http_client = tornado.httpclient.AsyncHTTPClient()
        request_headers = {
            'Origin': 'http://www.bilidown.tv',
            'X-Forwarded-For': self.request.remote_ip
        }
        request_options = {
            'url': url,
            'method': 'GET',
            'headers': request_headers,
            'user_agent': self.USER_AGENT,
            'connect_timeout': 60,
            'request_timeout': 60,
            'follow_redirects': True,
            'max_redirects': 16,
            'use_gzip': True,
            'allow_ipv6': True
        }
        response = yield http_client.fetch(tornado.httpclient.HTTPRequest(**request_options))
        if response.error:
            raise response.error
        raise tornado.gen.Return(response.body.decode('utf-8', 'replace'))

    def verify_rate(self):
        try:
            MainHandler.last_visited
        except AttributeError:
            MainHandler.last_visited = []
        current_time = time.time()
        threshold_time = current_time-20
        result = True
        for i, (last_time, ip) in enumerate(MainHandler.last_visited):
            if last_time < threshold_time:
                del MainHandler.last_visited[i]
            elif ip == self.request.remote_ip:
                result = False
            else:
                break
        if result:
            MainHandler.last_visited.append((current_time, self.request.remote_ip))
        else:
            self.print_error(e=ValueError('请求太频繁，请稍候30秒'), status=429)
        return result

    @tornado.gen.coroutine
    def verify_cookie(self):
        '''Visit COOKIE_VERIFIER to verify cookie'''
        assert self.COOKIE_VERIFIER.startswith('/')
        http_client = tornado.httpclient.AsyncHTTPClient()
        request_headers = {
            'Cookie': '; '.join(self.request.headers.get_list('Cookie')),
            'X-Forwarded-For': self.request.remote_ip
        }
        request_options = {
            'url': 'http://%s%s' % (self.request.headers.get('Host', 'localhost'), self.COOKIE_VERIFIER),
            'method': 'GET',
            'headers': request_headers,
            'user_agent': self.request.headers.get('User-Agent', self.USER_AGENT),
            'connect_timeout': 60,
            'request_timeout': 60,
            'follow_redirects': False,
            'allow_ipv6': True
        }
        try:
            response = yield http_client.fetch(tornado.httpclient.HTTPRequest(**request_options))
            if response.error:
                raise response.error
        except tornado.httpclient.HTTPError as error:
            if error.response and 'Location' in error.response.headers:
                self.set_header('Location', error.response.headers['Location'])
            self.print_error(e=ValueError('认证失败'), status=error.code)
            return False
        return True


class CookieVerifyHandler(tornado.web.RequestHandler):
    def get(self):
        self.write('OK')


if __name__ == '__main__':
    tornado.options.define("debug", default=False, help="enabling debugging features", type=bool)
    tornado.options.define("port", default=7777, help="run on the given port", type=int)
    tornado.options.parse_command_line()
    tornado.httpclient.AsyncHTTPClient.configure("tornado.curl_httpclient.CurlAsyncHTTPClient")
    app_settings = {
        'gzip': True,
        'debug': tornado.options.options.debug,
        'template_path': 'template',
        'static_path': 'static'
    }
    application = tornado.web.Application([
        ('/danmaku2ass', MainHandler),
        ('/cookie_verify', CookieVerifyHandler),
        ('/.*', tornado.web.RedirectHandler, {'url': '/danmaku2ass'})
    ], **app_settings)
    server = tornado.httpserver.HTTPServer(application, xheaders=True)
    server.bind(tornado.options.options.port, 'localhost')
    server.start(1)
    tornado.ioloop.IOLoop.instance().start()
