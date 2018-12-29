# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Mapping
from unittest import mock

import jinja2

import pytest

from google.protobuf import descriptor_pb2

from gapic.generator import generator
from gapic.schema import api
from gapic.schema import naming
from gapic.schema import wrappers


def test_custom_template_directory():
    # Create a generator.
    g = generator.Generator(templates='/templates/')

    # Assert that the Jinja loader will pull from the correct location.
    assert g._env.loader.searchpath == ['/templates/']


def test_get_response():
    g = generator.Generator()
    with mock.patch.object(jinja2.FileSystemLoader, 'list_templates') as lt:
        lt.return_value = ['foo/bar/baz.py.j2']
        with mock.patch.object(jinja2.Environment, 'get_template') as gt:
            gt.return_value = jinja2.Template('I am a template result.')
            cgr = g.get_response(api_schema=make_api())
    lt.assert_called_once()
    gt.assert_called_once()
    assert len(cgr.file) == 1
    assert cgr.file[0].name == 'foo/bar/baz.py'
    assert cgr.file[0].content == 'I am a template result.\n'


def test_get_response_ignores_private_files():
    g = generator.Generator()
    with mock.patch.object(jinja2.FileSystemLoader, 'list_templates') as lt:
        lt.return_value = ['foo/bar/baz.py.j2', 'foo/bar/_base.py.j2']
        with mock.patch.object(jinja2.Environment, 'get_template') as gt:
            gt.return_value = jinja2.Template('I am a template result.')
            cgr = g.get_response(api_schema=make_api())
    lt.assert_called_once()
    gt.assert_called_once()
    assert len(cgr.file) == 1
    assert cgr.file[0].name == 'foo/bar/baz.py'
    assert cgr.file[0].content == 'I am a template result.\n'


def test_get_response_fails_invalid_file_paths():
    g = generator.Generator()
    with mock.patch.object(jinja2.FileSystemLoader, 'list_templates') as lt:
        lt.return_value = ['foo/bar/$service/$proto/baz.py.j2']
        with pytest.raises(ValueError) as ex:
            g.get_response(api_schema=make_api())
        assert '$proto' in str(ex) and '$service' in str(ex)


def test_get_response_enumerates_services():
    g = generator.Generator()
    with mock.patch.object(jinja2.FileSystemLoader, 'list_templates') as lt:
        lt.return_value = ['foo/$service/baz.py.j2']
        with mock.patch.object(jinja2.Environment, 'get_template') as gt:
            gt.return_value = jinja2.Template('Service: {{ service.name }}')
            cgr = g.get_response(api_schema=make_api(make_proto(
                descriptor_pb2.FileDescriptorProto(service=[
                    descriptor_pb2.ServiceDescriptorProto(name='Spam'),
                    descriptor_pb2.ServiceDescriptorProto(name='EggsService'),
                ]),
            )))
    assert len(cgr.file) == 2
    assert {i.name for i in cgr.file} == {
        'foo/spam/baz.py',
        'foo/eggs_service/baz.py',
    }


def test_get_response_enumerates_proto():
    g = generator.Generator()
    with mock.patch.object(jinja2.FileSystemLoader, 'list_templates') as lt:
        lt.return_value = ['foo/$proto.py.j2']
        with mock.patch.object(jinja2.Environment, 'get_template') as gt:
            gt.return_value = jinja2.Template('Proto: {{ proto.module_name }}')
            cgr = g.get_response(api_schema=make_api(
                make_proto(descriptor_pb2.FileDescriptorProto(name='a.proto')),
                make_proto(descriptor_pb2.FileDescriptorProto(name='b.proto')),
            ))
    assert len(cgr.file) == 2
    assert {i.name for i in cgr.file} == {'foo/a.py', 'foo/b.py'}


def test_get_response_divides_subpackages():
    g = generator.Generator()
    api_schema = api.API.build([
        descriptor_pb2.FileDescriptorProto(
            name='top.proto',
            package='foo.v1',
            service=[descriptor_pb2.ServiceDescriptorProto(name='Top')],
        ),
        descriptor_pb2.FileDescriptorProto(
            name='a/spam/ham.proto',
            package='foo.v1.spam',
            service=[descriptor_pb2.ServiceDescriptorProto(name='Bacon')],
        ),
        descriptor_pb2.FileDescriptorProto(
            name='a/eggs/yolk.proto',
            package='foo.v1.eggs',
            service=[descriptor_pb2.ServiceDescriptorProto(name='Scramble')],
        ),
    ], package='foo.v1')
    with mock.patch.object(jinja2.FileSystemLoader, 'list_templates') as lt:
        lt.return_value = [
            'foo/$sub/types/$proto.py.j2',
            'foo/$sub/services/$service.py.j2',
        ]
        with mock.patch.object(jinja2.Environment, 'get_template') as gt:
            gt.return_value = jinja2.Template("""
                {{- '' }}Subpackage: {{ '.'.join(api.subpackage_view) }}
            """.strip())
            cgr = g.get_response(api_schema=api_schema)
    assert len(cgr.file) == 6
    assert {i.name for i in cgr.file} == {
        'foo/types/top.py',
        'foo/services/top.py',
        'foo/spam/types/ham.py',
        'foo/spam/services/bacon.py',
        'foo/eggs/types/yolk.py',
        'foo/eggs/services/scramble.py',
    }


def test_get_filename():
    g = generator.Generator()
    template_name = '$namespace/$name_$version/foo.py.j2'
    assert g._get_filename(template_name,
        api_schema=make_api(
            naming=make_naming(namespace=(), name='Spam', version='v2'),
        )
    ) == 'spam_v2/foo.py'


def test_get_filename_with_namespace():
    g = generator.Generator()
    template_name = '$namespace/$name_$version/foo.py.j2'
    assert g._get_filename(template_name,
        api_schema=make_api(
            naming=make_naming(
                name='Spam',
                namespace=('Ham', 'Bacon'),
                version='v2',
            ),
        ),
    ) == 'ham/bacon/spam_v2/foo.py'


def test_get_filename_with_service():
    g = generator.Generator()
    template_name = '$name/$service/foo.py.j2'
    assert g._get_filename(
        template_name,
        api_schema=make_api(
            naming=make_naming(namespace=(), name='Spam', version='v2'),
        ),
        context={
            'service': wrappers.Service(
                methods=[],
                service_pb=descriptor_pb2.ServiceDescriptorProto(name='Eggs'),
            ),
        }
    ) == 'spam/eggs/foo.py'


def test_get_filename_with_proto():
    file_pb2 = descriptor_pb2.FileDescriptorProto(
        name='bacon.proto',
        package='foo.bar.v1',
    )
    api = make_api(
        make_proto(file_pb2),
        naming=make_naming(namespace=(), name='Spam', version='v2'),
    )

    g = generator.Generator()
    assert g._get_filename(
        '$name/types/$proto.py.j2',
        api_schema=api,
        context={'proto': api.protos['bacon.proto']},
    ) == 'spam/types/bacon.py'


def test_get_filename_with_proto_and_sub():
    file_pb2 = descriptor_pb2.FileDescriptorProto(
        name='bacon.proto',
        package='foo.bar.v2.baz',
    )
    naming = make_naming(
        namespace=('Foo',),
        name='Bar',
        proto_package='foo.bar.v2',
        version='v2',
    )
    api = make_api(
        make_proto(file_pb2, naming=naming),
        naming=naming,
        subpackage_view=('baz',),
    )

    g = generator.Generator()
    assert g._get_filename(
        '$name/types/$sub/$proto.py.j2',
        api_schema=api,
        context={'proto': api.protos['bacon.proto']},
    ) == 'bar/types/baz/bacon.py'


def make_proto(file_pb: descriptor_pb2.FileDescriptorProto,
        file_to_generate: bool = True, prior_protos: Mapping = None,
        naming: naming.Naming = None,
        ) -> api.Proto:
    prior_protos = prior_protos or {}
    return api._ProtoBuilder(file_pb,
        file_to_generate=file_to_generate,
        naming=naming or make_naming(),
        prior_protos=prior_protos,
    ).proto


def make_api(*protos, naming: naming.Naming = None, **kwargs) -> api.API:
    return api.API(
        naming=naming or make_naming(),
        all_protos={i.name: i for i in protos},
        **kwargs
    )


def make_naming(**kwargs) -> naming.Naming:
    kwargs.setdefault('name', 'Hatstand')
    kwargs.setdefault('namespace', ('Google', 'Cloud'))
    kwargs.setdefault('version', 'v1')
    kwargs.setdefault('product_name', 'Hatstand')
    kwargs.setdefault('product_url', 'https://cloud.google.com/hatstand/')
    return naming.Naming(**kwargs)
