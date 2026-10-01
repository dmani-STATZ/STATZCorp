"""Management command to probe Microsoft Graph for SharePoint enumeration alternatives."""

import math
import time
from django.conf import settings
from django.core.management.base import BaseCommand
import requests

from contracts.services.folder_scan.graph_walker import GraphClient
from contracts.services.sharepoint_service import GRAPH_BASE, _auth_headers

class Command(BaseCommand):
    help = 'Probe Microsoft Graph endpoints for folder scanning alternatives.'

    def add_arguments(self, parser):
        parser.add_argument('--pages', type=int, default=25, help='Max pages for pass A')
        parser.add_argument('--items', type=int, default=297041, help='Total items for projections')
        parser.add_argument(
            '--modes',
            type=str,
            default='root,drive-delta,list-items,list-delta',
            help='Comma-separated list of modes to run'
        )

    def handle(self, *args, **options):
        pages_arg = min(options['pages'], 100)
        items_arg = options['items']
        modes = [m.strip() for m in options['modes'].split(',') if m.strip()]

        drive_id = getattr(settings, 'SHAREPOINT_DRIVE_ID', '')
        if not drive_id:
            self.stdout.write("ERROR: SHAREPOINT_DRIVE_ID not configured")
            return

        client = GraphClient()

        list_id = None
        site_id = None

        for mode in modes:
            self.stdout.write(f"== {mode.upper()} ==")
            try:
                if mode == 'root':
                    self._run_root(client, drive_id)
                elif mode == 'drive-delta':
                    self._run_drive_delta(client, drive_id, pages_arg, items_arg)
                elif mode == 'list-items':
                    list_id, site_id = self._run_list_items(client, drive_id, pages_arg, items_arg)
                elif mode == 'list-delta':
                    self._run_list_delta(client, list_id, site_id, items_arg)
            except Exception as e:
                self.stdout.write(f"ERROR: {type(e).__name__}: {str(e)}")

        self.stdout.write("== END ==")

    def _time_get(self, client, url):
        t0 = time.monotonic()
        resp = client.get(url)
        dt = time.monotonic() - t0
        return resp.json(), dt

    def _run_root(self, client, drive_id):
        url = f"{GRAPH_BASE}/drives/{drive_id}/root/children?$select=name,folder&$top=200"
        data, _ = self._time_get(client, url)
        for item in data.get('value', []):
            name = item.get('name', '')
            count = item.get('folder', {}).get('childCount', 0)
            self.stdout.write(f"{name}: {count}")

    def _run_drive_delta(self, client, drive_id, max_pages, total_items):
        select = "id,name,folder,file,deleted,root,parentReference,webUrl"
        base_url = f"{GRAPH_BASE}/drives/{drive_id}/root/delta?$select={select}"

        pass_a = self._drive_delta_pass(client, f"{base_url}&$top=200", max_pages)
        pass_b = self._drive_delta_pass(client, f"{base_url}&$top=1000", 3)

        self._print_drive_delta_stats("Pass A", pass_a)
        self._print_drive_delta_stats("Pass B", pass_b)

        if pass_a['pages'] > 0:
            for i, f in enumerate(pass_a['samples']):
                self.stdout.write(f"Sample folder {i+1}: {f['id']} | {f.get('name', '')} | {f.get('parentReference', {}).get('id', '')}")

        self._project("drive-delta", pass_a, pass_b, total_items)

    def _drive_delta_pass(self, client, start_url, max_pages):
        url = start_url
        pages = 0
        total_time = 0.0
        items_count = 0
        folders = 0
        files = 0
        deleted = 0
        with_path = 0
        with_parent_id = 0
        reached_delta = False
        samples = []

        while url and pages < max_pages:
            data, dt = self._time_get(client, url)
            pages += 1
            total_time += dt
            items = data.get('value', [])
            items_count += len(items)

            for item in items:
                if 'deleted' in item:
                    deleted += 1
                elif 'folder' in item or 'root' in item:
                    folders += 1
                    if len(samples) < 3:
                        samples.append(item)
                elif 'file' in item:
                    files += 1

                pref = item.get('parentReference', {})
                if 'path' in pref:
                    with_path += 1
                if 'id' in pref:
                    with_parent_id += 1

            if '@odata.deltaLink' in data:
                reached_delta = True
                break
            url = data.get('@odata.nextLink')

        return {
            'pages': pages,
            'total_time': total_time,
            'items_count': items_count,
            'folders': folders,
            'files': files,
            'deleted': deleted,
            'with_path': with_path,
            'with_parent_id': with_parent_id,
            'reached_delta': reached_delta,
            'samples': samples,
        }

    def _print_drive_delta_stats(self, pass_name, stats):
        pages = stats['pages']
        if pages == 0:
            return
        avg_sec = stats['total_time'] / pages
        avg_items = stats['items_count'] / pages
        self.stdout.write(f"{pass_name} pages fetched: {pages}")
        self.stdout.write(f"{pass_name} average seconds per page: {avg_sec:.2f}")
        self.stdout.write(f"{pass_name} average items per page: {avg_items:.1f}")
        self.stdout.write(f"{pass_name} total folders: {stats['folders']}")
        self.stdout.write(f"{pass_name} total files: {stats['files']}")
        self.stdout.write(f"{pass_name} total deleted: {stats['deleted']}")
        self.stdout.write(f"{pass_name} items with parentReference.path: {stats['with_path']}")
        self.stdout.write(f"{pass_name} items with parentReference.id: {stats['with_parent_id']}")
        self.stdout.write(f"{pass_name} reached deltaLink: {stats['reached_delta']}")

    def _run_list_items(self, client, drive_id, max_pages, total_items):
        list_url = f"{GRAPH_BASE}/drives/{drive_id}/list?$select=id,name,displayName,parentReference"
        data, _ = self._time_get(client, list_url)
        list_id = data.get('id', '')
        site_id = data.get('parentReference', {}).get('siteId', '')
        if not site_id:
            site_id = getattr(settings, 'SHAREPOINT_SITE_ID', '')
        
        self.stdout.write(f"list_id: {list_id}")
        self.stdout.write(f"site_id: {site_id}")

        if not list_id or not site_id:
            return list_id, site_id

        select = "$select=id&$expand=fields($select=FileRef,FileLeafRef,FSObjType),driveItem($select=id)"
        base_url = f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items?{select}"

        pass_a = self._list_items_pass(client, f"{base_url}&$top=200", max_pages)
        pass_b = self._list_items_pass(client, f"{base_url}&$top=1000", 3)

        self._print_list_items_stats("Pass A", pass_a)
        if pass_b['pages'] > 0:
            self.stdout.write(f"Pass B items per page: {pass_b['items_count'] / pass_b['pages']:.1f}")

        if pass_a['pages'] > 0:
            for i, f in enumerate(pass_a['samples']):
                fileref = f.get('fields', {}).get('FileRef', '')
                did = f.get('driveItem', {}).get('id', '')
                self.stdout.write(f"Sample folder {i+1}: {fileref} | {did}")

        # Filter tests
        filter_url = f"{base_url}&$filter=fields/FSObjType eq 1&$top=10"
        self._run_filter_test("Filter test 1", client, filter_url, {})
        self._run_filter_test("Filter test 2", client, filter_url, {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"})

        self._project("list-items", pass_a, pass_b, total_items)
        return list_id, site_id

    def _list_items_pass(self, client, start_url, max_pages):
        url = start_url
        pages = 0
        total_time = 0.0
        items_count = 0
        folders = 0
        files = 0
        with_fileref = 0
        with_drive_item_id = 0
        samples = []

        while url and pages < max_pages:
            data, dt = self._time_get(client, url)
            pages += 1
            total_time += dt
            items = data.get('value', [])
            items_count += len(items)

            for item in items:
                fields = item.get('fields', {})
                obj_type = fields.get('FSObjType')
                if obj_type == 1 or obj_type == "1":
                    folders += 1
                    if len(samples) < 3:
                        samples.append(item)
                else:
                    files += 1

                if 'FileRef' in fields:
                    with_fileref += 1
                if item.get('driveItem', {}).get('id'):
                    with_drive_item_id += 1

            url = data.get('@odata.nextLink')

        return {
            'pages': pages,
            'total_time': total_time,
            'items_count': items_count,
            'folders': folders,
            'files': files,
            'with_fileref': with_fileref,
            'with_drive_item_id': with_drive_item_id,
            'samples': samples,
        }

    def _print_list_items_stats(self, pass_name, stats):
        pages = stats['pages']
        if pages == 0:
            return
        avg_sec = stats['total_time'] / pages
        avg_items = stats['items_count'] / pages
        self.stdout.write(f"{pass_name} average seconds per page: {avg_sec:.2f}")
        self.stdout.write(f"{pass_name} average items per page: {avg_items:.1f}")
        self.stdout.write(f"{pass_name} total folders: {stats['folders']}")
        self.stdout.write(f"{pass_name} total files: {stats['files']}")
        self.stdout.write(f"{pass_name} items with FileRef: {stats['with_fileref']}")
        self.stdout.write(f"{pass_name} items with driveItem.id: {stats['with_drive_item_id']}")

    def _run_filter_test(self, name, client, url, headers):
        self.stdout.write(f"{name}:")
        req_headers = _auth_headers(client.token())
        req_headers.update(headers)
        t0 = time.monotonic()
        resp = requests.get(url, headers=req_headers, timeout=60)
        dt = time.monotonic() - t0
        self.stdout.write(f"  HTTP status: {resp.status_code}")
        
        try:
            data = resp.json()
        except ValueError:
            data = {}

        if resp.status_code == 200:
            count = len(data.get('value', []))
            self.stdout.write(f"  item count: {count}")
        else:
            err = data.get('error', {})
            code = err.get('code', '')
            inner = err.get('innerError', {}).get('code', '')
            msg = err.get('message', '')[:300]
            self.stdout.write(f"  error.code: {code}")
            self.stdout.write(f"  error.innerError.code: {inner}")
            self.stdout.write(f"  error.message: {msg}")

    def _run_list_delta(self, client, list_id, site_id, total_items):
        if not list_id or not site_id:
            self.stdout.write("ERROR: Missing list_id or site_id")
            return
        
        url = f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items/delta?$expand=fields($select=FileRef,FSObjType),driveItem($select=id)&$top=200"
        pages = 0
        total_time = 0.0
        items_count = 0
        with_fileref = 0
        has_next = False
        has_delta = False

        while url and pages < 3:
            t0 = time.monotonic()
            resp = requests.get(url, headers=_auth_headers(client.token()), timeout=60)
            dt = time.monotonic() - t0

            if resp.status_code < 200 or resp.status_code >= 300:
                self.stdout.write(f"HTTP status: {resp.status_code}")
                try:
                    err = resp.json().get('error', {})
                except ValueError:
                    err = {}
                self.stdout.write(f"error.code: {err.get('code', '')}")
                self.stdout.write(f"error.message: {err.get('message', '')}")
                break

            data = resp.json()

            pages += 1
            total_time += dt
            items = data.get('value', [])
            items_count += len(items)

            for item in items:
                if 'FileRef' in item.get('fields', {}):
                    with_fileref += 1
            
            has_next = '@odata.nextLink' in data
            has_delta = '@odata.deltaLink' in data
            url = data.get('@odata.nextLink')

        if pages > 0:
            avg_sec = total_time / pages
            avg_items = items_count / pages
            self.stdout.write(f"average seconds per page: {avg_sec:.2f}")
            self.stdout.write(f"average items per page: {avg_items:.1f}")
            self.stdout.write(f"items with FileRef: {with_fileref}")
            self.stdout.write(f"has @odata.nextLink: {has_next}")
            self.stdout.write(f"has @odata.deltaLink: {has_delta}")
            
            # Projections for list-delta
            pass_fake = {'pages': pages, 'items_count': items_count, 'total_time': total_time}
            self._project("list-delta", pass_fake, {'pages': 0}, total_items)


    def _project(self, mode, pass_a, pass_b, total_items):
        if pass_a['pages'] == 0 and pass_b['pages'] == 0:
            return

        avg_items_a = pass_a['items_count'] / pass_a['pages'] if pass_a['pages'] > 0 else 0
        avg_items_b = pass_b['items_count'] / pass_b['pages'] if pass_b['pages'] > 0 else 0
        avg_sec_a = pass_a['total_time'] / pass_a['pages'] if pass_a['pages'] > 0 else 0

        use_pass = 'A'
        avg_items = avg_items_a
        if pass_b['pages'] > 0 and avg_items_b > avg_items_a:
            use_pass = 'B'
            avg_items = avg_items_b
        
        if avg_items <= 0:
            return

        projected_pages = math.ceil(total_items / avg_items)
        projected_minutes = (projected_pages * avg_sec_a) / 60.0

        self.stdout.write(f"Projections ({mode}):")
        self.stdout.write(f"  projected_pages: {projected_pages} (using Pass {use_pass} page size)")
        self.stdout.write(f"  projected_minutes: {projected_minutes:.1f}")

