import os
import logging
from werkzeug.datastructures import FileStorage as FlaskFileStorage
import ckan.lib.uploader as uploader
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckan.common import c
import requests
from PIL import Image
from PIL import PngImagePlugin, JpegImagePlugin
from io import StringIO, BytesIO

logger = logging.getLogger(__name__)

def thumbnail_url(package_id):
    '''Returns the url of a thumbnail for a dataset. 

    Looks for a resource "thumbnail.png" in a dataset.
    Will generate a thumbnail and save it to the dataset if there isn't one already.

    To change this setting add to the
    [app:main] section of your CKAN config file::

      ckan.datasetthumbnail.show_thumbnail = true

    :rtype: string
    '''

    try:
        cfg_show = toolkit.config.get('ckan.datasetthumbnail.show_thumbnail', False)
        show_thumbnail = toolkit.asbool(cfg_show)

        cfg_auto_generate = toolkit.config.get('ckan.datasetthumbnail.auto_generate', False)
        auto_generate = toolkit.asbool(cfg_auto_generate)

        if not show_thumbnail:
            return None

        if package_id == None or len(package_id) == 0:
            return '/image-icon.png'

        package = toolkit.get_action('package_show')(data_dict={'id': package_id})
        
        filename = toolkit.config.get('ckan.datasetthumbnail.thumbnail.filename', 'thumbnail.jpg')
        for resource in package['resources']:
            if resource['name'] == filename or resource['name'].startswith('thumbnail'):
                return resource['url']

        #if there's no thumbnail then automatically generate one and add it to the dataset
        url = None

        if auto_generate:
            if c.user != None and len(c.user) > 0:
                url = create_thumbnail(package_id, filename=filename)

        return url or toolkit.config.get('ckan.datasetthumbnail.fallback_thumbnail', '/image-icon.png')
    except Exception:
        return None

def create_thumbnail(package_id, resource_id=None, width=None, height=None, filename=None):
    '''Creates a thumbnail in a dataset and returns its url

    :rtype: string
    '''
    if c.user == None or len(c.user) == 0:
        return None

    if width == None:
        cfg_width = toolkit.config.get('ckan.datasetthumbnail.thumbnail_width', 140)
        width = toolkit.asint(cfg_width)

    if height == None:
        cfg_height = toolkit.config.get('ckan.datasetthumbnail.thumbnail_height', int(width * 1.415))
        height = toolkit.asint(cfg_height)

    package = toolkit.get_action('package_show')(
        context={'ignore_auth': True}, 
        data_dict={'id': package_id})

    resource = None    
    if resource_id != None:
        resource = toolkit.get_action('resource_show')(
            context={'ignore_auth': True}, 
            data_dict={'id': resource_id})        

    if resource == None:
        for pkg_resource in package['resources']:
            if pkg_resource['format'] == 'JPEG' or pkg_resource['format'] == 'PNG':
                resource = pkg_resource
                break

    image = None
    original_fp = None

    if resource != None:
        headers = {}
        if resource['url_type'] == 'upload':
            upload = uploader.get_resource_uploader(resource)
            filepath = upload.get_path(resource[u'id'])
            # filepath = get_path(resource['id'])

            try:
                image = Image.open(filepath)
            except IOError:
                #if an image can't be parsed from the response...
                return None

        else:
            try:
                response = requests.get(resource['url'], headers=headers, stream=True)
            except requests.exceptions.RequestException:
                # Silently fail on any request exception on the basis that it's
                # better to have a working page with missing thumbnails than a
                # broken one.
                return

            if response.status_code == 200:
                original_fp = StringIO()  #create an in-memory file object in which to save the image

                logger.info('Loading image from %s', resource['url'])
                for chunk in response.iter_content(1024 * 32):
                    original_fp.write(chunk)
                original_fp.flush()

                try:
                    image = Image.open(original_fp.buffer)
                except IOError:
                    #if an image can't be parsed from the response...
                    return None
            
        if image == None:
            return None

        image.thumbnail((width, height))

        thumbnail_fp = BytesIO()
        format = toolkit.config.get('ckan.datasetthumbnail.thumbnail.format', 'JPEG')
        quality = toolkit.asint(toolkit.config.get('ckan.datasetthumbnail.thumbnail.quality', 70))
        filename = filename or toolkit.config.get('ckan.datasetthumbnail.thumbnail.filename', 'thumbnail.jpg')
        image.save(thumbnail_fp, format=format, quality=quality)
        thumbnail_fp.name = filename

        thumbnail_resource = {}
        thumbnail_resource['package_id'] = package['id']
        thumbnail_resource['url'] = filename
        thumbnail_resource['url_type'] = 'upload'
        thumbnail_resource['format'] = format.lower()
        thumbnail_resource['name'] = thumbnail_fp.name
        thumbnail_resource['upload'] = FlaskFileStorage(stream=thumbnail_fp)

        created_resource = toolkit.get_action('resource_create')(context={'ignore_auth': True}, data_dict=thumbnail_resource)
        thumbnail_fp.close()
        if (original_fp != None):
            original_fp.close()

        return created_resource['url']

    return None

def get_directory(id):
    directory = os.path.join('/var/lib/ckan/resources/',
                                id[0:3], id[3:6])
    return directory

def get_path(id):
    directory = get_directory(id)
    filepath = os.path.join(directory, id[6:])
    return filepath

class DatasetthumbnailPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IActions)


    # IConfigurer
    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'datasetthumbnail')

    #ITemplateHelpers
    def get_helpers(self):
        return {
            'thumbnail_url': thumbnail_url
        }

    #IActions
    def get_actions(self):
        return {
            'create_thumbnail':
            create_thumbnail,
        }
