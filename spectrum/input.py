from os import path
import random
import string
import requests
from spectrum import aws, logger
from spectrum.config import SETTINGS
from econtools import econ_article_feeder
from pollute import modified_environ
import mechanicalsoup

LOGGER = logger.logger(__name__)

class InputBucket:
    def __init__(self, s3, bucket_name):
        self._s3 = s3
        self._bucket_name = bucket_name

    def upload(self, filename, id):
        self._s3.meta.client.upload_file(filename, self._bucket_name, path.basename(filename))
        LOGGER.info("Uploaded %s to %s", filename, self._bucket_name, extra={'id': id})

    def name(self):
        return self._bucket_name

class Dashboard:
    def __init__(self, host, user, password):
        self._host = host
        self._user = user
        self._password = password

    def publish(self, id, version, run):
        template = "%s/api/queue_article_publication"
        url = template % self._host
        body = {}
        body = {'articles': [{'id': id, 'version': version, 'run': run}]}
        response = requests.post(url, auth=(self._user, self._password), json=body, verify=False)
        assert response.status_code == 200, ("Response status was %s: %s" % (response.status_code, response.text))
        LOGGER.info(
            "Pressed Publish for %s version %s run %s on dashboard",
            url,
            version,
            run,
            extra={'id': id}
        )

class SilentCorrectionWorkflowStarter:
    def __init__(self, aws_access_key_id, aws_secret_access_key, region_name, input_bucket_name, queue_name, workflow_name):
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._region_name = region_name
        self._input_bucket_name = input_bucket_name
        self._queue_name = queue_name
        self._workflow_name = workflow_name

    def article(self, filename):
        with modified_environ(added={'AWS_ACCESS_KEY_ID': self._aws_access_key_id, 'AWS_SECRET_ACCESS_KEY': self._aws_secret_access_key, 'AWS_DEFAULT_REGION': self._region_name}):
            econ_article_feeder.feed_econ(
                self._input_bucket_name,
                self._queue_name,
                rate=1,
                prefix=filename,
                workflow_name='SilentCorrectionsIngest'
            )

class JournalCms:
    def __init__(self, host, user, password):
        self._host = host
        self._user = user
        self._password = password

    def login(self):
        browser = mechanicalsoup.Browser()
        login_url = "%s/user/login" % self._host
        login_page = browser.get(login_url)
        form = mechanicalsoup.Form(login_page.soup.form)
        form.input({'name': self._user, 'pass': self._password})
        response = browser.submit(form, login_page.url)
        assert _journal_cms_page_title(response.soup) == self._user
        return JournalCmsSession(self._host, browser)

class JournalCmsSession:
    def __init__(self, host, browser):
        self._host = host
        self._browser = browser

    def create_blog_article(self, title, text='Lorem ipsum', image=None):
        create_url = "%s/node/add/blog_article" % self._host
        create_page = self._browser.get(create_url)
        form = mechanicalsoup.Form(create_page.soup.form)
        form.input({'title[0][value]': title})
        LOGGER.info("Adding paragraph")
        self._choose_submit(form, 'field_content_paragraph_add_more')
        response = self._browser.submit(form, create_page.url)
        form = mechanicalsoup.Form(response.soup.form)
        form.textarea({'field_content[0][subform][field_block_html][0][value]': text})
        if image:
            form.attach({'files[field_image_0]': image})
            LOGGER.info("Adding image")
            self._choose_submit(form, 'op', value='Upload')

        LOGGER.info("Saving form")
        self._choose_submit(form, 'op', value='Save and publish')
        # not sure why, but `data` here is necessary
        response = self._browser.submit(form, create_page.url, data={'op': 'Save and publish'})
        assert _journal_cms_page_title(response.soup) == title
        #check https://end2end--journal-cms.elifesciences.org/admin/content?status=All&type=All&title=b9djvu04y6v1t4kug4ts8kct5pagf8&langcode=All
        # but in checks module
        # TODO: return id and/or node id

    def create_article_fragment(self, id, image):
        create_url = "%s/admin/structure/article_fragment/add" % self._host
        create_page = self._browser.get(create_url)
        form = mechanicalsoup.Form(create_page.soup.form)
        form.input({'name[0][value]': id})
        form.attach({'files[image_0]': image})
        LOGGER.info(
            "Submitting thumbnail %s",
            image,
            extra={'id': id}
        )
        self._choose_submit(form, 'image_0_upload_button', value='Upload')
        response = self._browser.submit(form, create_page.url)
        form = mechanicalsoup.Form(response.soup.form)


        form.attach({'files[banner_image_0]': image})

        LOGGER.info(
            "Submitting banner %s",
            image,
            extra={'id': id}
        )
        self._choose_submit(form, 'banner_image_0_upload_button', value='Upload')
        response = self._browser.submit(form, create_page.url)
        form = mechanicalsoup.Form(response.soup.form)
        LOGGER.info(
            "Saving form",
            extra={'id': id}
        )
        response = self._browser.submit(form, create_page.url, data={'op': 'Save'})
        img = response.soup.select_one(".field--name-banner-image img")
        assert "king_county" in img.get('src')
        LOGGER.info(
            "Tag: %s",
            img,
            extra={'id': id}
        )

    def _choose_submit(self, wrapped_form, name, value=None):
        """Fixed version of mechanicalsoup.Form.choose_submit()

        https://github.com/hickford/MechanicalSoup/issues/61"""

        form = wrapped_form.form

        criteria = {"name":name}
        if value:
            criteria['value'] = value
        chosen_submit = form.find("input", criteria)

        for inp in form.select("input"):
            if inp.get('type') != 'submit':
                continue
            if inp == chosen_submit:
                continue
            del inp['name']

def _journal_cms_page_title(soup):
    # <h1 class="js-quickedit-page-title title page-title"><span data-quickedit-field-id="node/1709/title/en/full" class="field field--name-title field--type-string field--label-hidden">Spectrum blog article: jvsfz4oj9vz9hk239fbpq4fbjc9yoh</span></h1>
    #<h1 class="js-quickedit-page-title title page-title">alfred</h1>
    return soup.find("h1", {"class": "page-title"}).text.strip()

def invented_word(length=30):
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))

PRODUCTION_BUCKET = InputBucket(aws.S3, SETTINGS['bucket_input'])
SILENT_CORRECTION_BUCKET = InputBucket(aws.S3, SETTINGS['bucket_silent_corrections'])
DASHBOARD = Dashboard(
    SETTINGS['dashboard_host'],
    SETTINGS['dashboard_user'],
    SETTINGS['dashboard_password']
)

SILENT_CORRECTION = SilentCorrectionWorkflowStarter(
    SETTINGS['aws_access_key_id'],
    SETTINGS['aws_secret_access_key'],
    SETTINGS['region_name'],
    SILENT_CORRECTION_BUCKET.name(),
    SETTINGS['queue_workflow_starter'],
    'SilentCorrectionsIngest'
)

JOURNAL_CMS = JournalCms(
    SETTINGS['journal_cms_host'],
    SETTINGS['journal_cms_user'],
    SETTINGS['journal_cms_password']
)
