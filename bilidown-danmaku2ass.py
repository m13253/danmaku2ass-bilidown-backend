#!/usr/bin/env python3

import concurrent.futures
import functools
import io

import curl  # https://github.com/m13253/pycurl-python3

import danmaku2ass  # https://github.com/m13253/danmaku2ass

import requests

import tornado.gen
import tornado.httpclient
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web


class MainHandler(tornado.web.RequestHandler):

    USER_AGENT = 'BiliDown.tv Danmaku2ASS Tornado/1.0 (sb@loli.con.sh) ; BiliDown.tv Bilibili Node.js API/0.2.0 (zyu@zhuogu.net)'
    MAX_THREADS = 8
    ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(MAX_THREADS)

    @tornado.gen.coroutine
    @tornado.web.asynchronous
    def get(self):
        # Parse arguments
        try:
            url = self.get_argument('url')
            width = int(self.get_argument('w'))
            if width <= 0: raise ValueError
            height = int(self.get_argument('h'))
            if height <= 0: raise ValueError
            reserve_blank = 0
            try:
                reserve_blank = int(self.get_argument('p'))
                if reserve_blank < 0: raise ValueError
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
                if font_size <= 0: raise ValueError
            except tornado.web.MissingArgumentError:
                pass
            text_opacity = 1.0
            try:
                text_opacity = float(self.get_argument('a'))
                if not (0 <= text_opacity <= 1): raise ValueError
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
                fi = io.StringIO((yield self.fetch_input(url, x_forwarded_for)))
            except Exception as e:
                return self.print_error(e)
        # Go and convert it
        self.progress_callback_called = False
        self.set_header('Content-Type', 'application/octet-stream')
        self.set_header('Content-Disposition', 'attachment; filename="%s"' % output_filename)
        fo = io.StringIO()
        try:
            self.ThreadPoolExecutor.submit(
                danmaku2ass.Danmaku2ASS, [fi], fo, width, height, reserve_blank, font_face, font_size, text_opacity, comment_duration, is_reduce_comments
            ).add_done_callback(
                lambda future: tornado.ioloop.IOLoop.instance().add_callback(functools.partial(self.danmaku2ass_finished, fo, future))
            )
        except Exception as e:
            return self.print_error(e)

    def danmaku2ass_finished(self, fo, future):
        e = future.exception()
        if e:
            return self.print_error(e)
        fo.seek(0)
        self.write(''.encode('utf-8-sig'))
        self.finish(fo.read())

    def print_error(self, e):
        self.set_status(500)
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.clear_header('Content-Disposition')
        self.render('error.html', e=e)

    @tornado.gen.coroutine
    def fetch_input(self, url, x_forwarded_for=None):
        '''Download comment file from the Internet'''
        if not url.startswith('http://comment.bilibili.tv/') and not url.startswith('http://comment.bilibili.cn/') and not url.startswith('http://www.bilidown.tv/'):
            raise ValueError('specified URL violates domain restriction')
        http_client = tornado.httpclient.AsyncHTTPClient()
        request_headers = {'Origin': 'http://www.bilidown.tv'}
        if x_forwarded_for is not None:
            request_headers['X-Forwarded-For'] = x_forwarded_for
        request_options = {
            'url': url,
            'method': 'GET',
            'headers': request_headers,
            'user_agent': MainHandler.USER_AGENT,
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
        else:
            raise tornado.gen.Return(response.body.decode('utf-8', 'replace'))


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
        ('/.*', tornado.web.RedirectHandler, {'url': '/danmaku2ass'})
    ], **app_settings)
    server = tornado.httpserver.HTTPServer(application, xheaders=True)
    server.bind(tornado.options.options.port, 'localhost')
    server.start(1)
    tornado.ioloop.IOLoop.instance().start()
