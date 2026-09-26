---
title: "自己写个python小程序下载忙总老井履虎尾等人的文章（答帖）"
slug: "自己写个python小程序下载忙总老井履虎尾等人的文章"
url: "/wxmang/replies/自己写个python小程序下载忙总老井履虎尾等人的文章/"
date: 2011-09-22
wx_author: "wxmang"
wx_kind: "reply-to-others"   # 本页是他在他人帖下的答帖，非独立文章
host_title: "自己写个python小程序下载忙总老井履虎尾等人的文章"
host_author: "瓦斯"
host_url: "https://wxmang.site/html/2_29882.html"
original_date: 2011-09-22
source_count: 1
reply_count: 2       # wxmang 的发言条数
reply_chars: 66
context_count: 11   # 被回应的读者发言条数（语境）
excludeFromSearch: true   # 隔离：与文集其余部分一致，不进全站搜索
---

> **原帖**：《自己写个python小程序下载忙总老井履虎尾等人的文章》 ｜ 作者：瓦斯 ｜ [原帖](https://wxmang.site/html/2_29882.html)
>
> 本页收录 **wxmang 在该帖下的答帖 2 条**（约 66 字），并保留他所回应的读者发言 11 条作为语境（共 4 位参与者）。
>
> 说明：`REPLY` 是该站对作者发言的记录方式，与页面署名无关——这些是 wxmang 的原话，原帖正文版权归原作者。

## 1

**问** ｜ *（无前文，作者主动发言）*

**答** ｜ wxmang ｜ 2011-09-22

这个厉害，我都是笨办法，一页页拷贝，累死人。

## 2

**问** ｜ 瓦斯、井底望天 ｜ 2011-09-23

程序改好了，在我这里试验10分钟之内可以下载忙总在丰言的121篇主题帖子。自动用忙总的帖子标题加上.txt作为文件名，默认保存到d:\wxmang目录中去。

如果你想试用，可以将下面的程序复制保存成d:\wxmang\wxmang.py，然后在一个DOS窗口中打入python d:\wxmang\wxmang.py就可以自动获得忙总所有的帖子了。

前提要求：你的电脑安装了python，这个程序不大，免费的，到处都可以下载到。

本程序设计默认下载忙总在丰言的主题帖子，如果要下载别人的，将其中的搜索链接改掉就可以了。

如果要用到丰言之外的论坛，需要稍作修改。

源程序贴在下面，欢迎报告错误，欢迎提出改进意见。

PHP 代码:

\#!/usr/bin/python

\#_-*-_coding:_UTF-8_-*-

import_io,sys,re

import_urllib.request,_urllib.parse,_urllib.error_#Python3

from_urllib.request_import_FancyURLopener

from_html.parser_import_HTMLParser

from_io_import_StringIO

output_path="D:\\wxmang\\"

url_author="http://www.fengyanforum.org/forum/search.php?action=results＆sid=5499aced95b497d5fb8a7f3f937b3ac2"

_#_搜索忙总所有主题帖子，搜索别人的修改此链接

def_get_web_content(url):

____myopener_=_FancyURLopener()__

____print("reading_%s..."_%(url))

____content_=_myopener.open(url).read().decode("utf-8")

____return_content

_

class_MyHTMLParser(HTMLParser):

____def___init__(self):_

________HTMLParser.__init__(self)

________self.text_=_StringIO()

________self.js=0

________self.links=[]

____def_handle_starttag(self,_tag,_attrs):

________if_tag=='a'_and_attrs:

____________link=attrs[0][1]

____________if_link_not_in_self.links_\

____________and_(("showthread.php?"_in_link_and_"page"_not_in_link_and_"lastpost"_not_in_link)_\

________________or_"search.php?"_in_link_and_"page"_in_link):

________________self.links.append(link)

____def_handle_data(self,_data):

________if_"＜!--"_in_data:

____________#_print("js_tag_begin")

____________self.js=1

________elif_"--＞"_in_data:

____________#_print("js_tag_end")

____________self.js=0

________else:_#_self.js==0:

____________self.text.write(data)

____def_get_text(self):

________return_self.text.getvalue()

____def_get_link(self):

________return_self.links

def_cleanline(line):

____line1=""

____while_1:

________line1=line.replace('\r\n\r\n\r\n','').replace('\t','').replace('\n\n\r','').replace('\r\n\r','').replace('\n\r\n','')

________if_line1!=line:

____________line=line1

________else:

____________break

____return_line1

________

def_save_list2file(filename,mylist):

____print("writing_%s_bytes_to_[_%s_]..."_%(len(mylist),filename))

____f_=_open(filename,"w")

____for_line_in_mylist:

________try:

____________f.write("%s"_%line)

________except_ValueError_as_e:

____________print(e)

____f.close()

____#_print("[_%s_]_closed."_%filename_)

____

def_save_url2file(output_path,url):

____content=get_web_content(url)

____title=content.splitlines()[3].replace("＜title＞","").replace("＜/title＞","").replace(":","").lstrip()

____#获取主帖标题，当作文件名

____p=MyHTMLParser()_

____p.feed(content)

____text_=_cleanline(p.get_text())

____save_list2file(output_path+title+".txt",text)

def_get_link2file(output_path,url_author):

____content=get_web_content(url_author)

____p=MyHTMLParser()_

____p.feed(content)

____links_=p.get_link()

____#_save_list2file(output_path+"urls.txt",links)

____return_links

links_page1=get_link2file(output_path,url_author)_#用搜索忙总主题的首页链接搜索，返回第一页的所有链接

url_authors=[]_#其余主题页的链接

urls=[]_#_具体主题帖子的具体链接

for____link_in_links_page1:

____if_"showthread.php?"_in_link:

________urls.append(link)_#_保存搜索结果第一页中的每个主题帖链接

____else:

________url_authors.append(link)_#保存搜索结果第一页中显示的其余页的链接

\#第一页的主帖链接搞定，其余搜索页的链接搞定

for_link_in_url_authors:_#对每个其余搜索页处理

____links_restpage=get_link2file(output_path,"http://www.fengyanforum.org/forum/"+link)_#_读取其余页的所有帖子链接

____for____link_in_links_restpage:

________if_"showthread.php?"_in_link:_#_只需要主帖子的链接了，不需要其余页的链接

____________urls.append(link)_

\#至此所有页的主帖链接搜集完毕

for_url_in_urls:_#对每个主帖的链接处理，保存结果到主帖标题的文件名中去

____save_url2file(output_path,"http://www.fengyanforum.org/forum/"+url)_

___

这两天，我正想着用python写个程序，往上贴帖子呢，呵呵。

忙兄，要是有兴趣学python，我可以教你。

对了前几天写一个管理VMware的程序，丫居然不支持python，害得我只好用Perl写了一个接口，痛苦啊，每一句都要加分号。

**答** ｜ wxmang ｜ 2011-09-24

谢谢，我暂时还是骑自行车吧，太快了我还控制不住。等你们把宝马开得顺畅了，我再来试试夏利。
