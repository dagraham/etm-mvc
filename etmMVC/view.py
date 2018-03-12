import pendulum
from pendulum import parse
from model import timestamp_from_eid, fmt_week, setup_logging, serialization, item_details, item_instances, beg_ends, fmt_extent, format_interval, getMonthWeeks, set_summary
from tinydb import TinyDB, Query, Storage
from tinydb.operations import delete
from tinydb.database import Table
from tinydb.storages import JSONStorage
from tinydb_serialization import Serializer
from tinydb_serialization import SerializationMiddleware
from tinydb_smartcache import SmartCacheTable
import json


from pprint import pprint

pendulum.set_formatter('alternative')

short_dt_fmt = "YYYY-MM-DD HH:mm"

ETMFMT = "YYYYMMDDTHHmm"

# each view in views: (row, eid) where row = ((sort), (path), (columns))

class Views(object):
    """
    TODO


    """


    def __init__(self):
        self.views = dict(
                created_view = [],   # row for id not changed with updates to that item
                index_view = [],
                modified_view = [],
                tags_view = [],
                weeks = {},
                weeks_view = [],
                agenda_view = [],
                next_view = [],
                someday_view = [],
                done_view = [],
                alerts = [],  
                instances = [],
                begins = [],    # (beg_dt, end_dt, id)
                busy = [],    # (beg_dt, end_dt, id)
                pastdues = [],  # (due_dt, id)
                relevant = [],  # (relevant_dt, id)
                )
        self.items = {}

        self.commands = dict(
                update_index = self._update_index_view,
                update_created = self._update_created_view,
                update_modified = self._update_modified_view,
                update_weeks = self._update_weeks,
                update_alerts = self._update_alerts,
                update_tags = self._update_tags_view,
                update_done = self._update_done_view,
                )
        self.today = None
        self.yearmonth = None
        self.beg_dt = self.end_dt = None
        self.bef_months = 5
        self.aft_months = 18
        self.modified = False
        self.maybe_refresh()

    def maybe_refresh(self):
        """
        If the current month has changed, reset the begin and end dates for the period to include the current month, the preceeding 5 months and the subsequent 18 months. Adjust the dates to include 6 complete weeks for each of the 24 months.
        """
        self.today = today = pendulum.today()
        # self.now = now = pendulum.now('Factory')
        yearmonth = (today.year, today.month)
        if yearmonth != self.yearmonth:
            # update year month
            self.yearmonth = yearmonth
            # get the first day of the current month
            n_beg = pendulum.create(year=yearmonth[0], month=yearmonth[1], day=1, hour=0, minute=0, second=0, microsecond=0)
            # get the first day of the month bef_months before
            b = n_beg.subtract(months=self.bef_months)
            # get the first day of the month aft_months after
            e = n_beg.add(months=self.aft_months)
            # get 12am Monday of the first week in the begin month
            self.beg_dt = b.subtract(days=b.weekday())
            # to include 6 weeks, get 12am Monday of the 6th week
            # after the first week in the end month
            e = e.subtract(days=e.weekday())
            self.end_dt = e.add(weeks=6)
            self.load_TinyDB()
            self.load_views()
            self._update_agenda()
            self.modified = True
        if today != self.today:
            self.today = today
            self._update_agenda()
            self.modified = True
        if self.modified:
            self._update_relevant()
            self._update_begins()
            self._update_pastdues()
            self.save_views()

    def save_views(self):
        with open('views.json', 'w') as jo:
            json.dump(self.views, jo, indent=1, sort_keys=True)


    def nothing_secheduled(self):
        pass

    def load_TinyDB(self):
        """
        Populate the views 
        """
        self.items = TinyDB('db.json', storage=serialization, default_table='items', indent=1, ensure_ascii=False)

    def load_views(self):
        for item in self.items:
            for cmd in self.commands:
                self.commands[cmd](item)
        for view in self.views:
            if isinstance(self.views[view], list):
                try:
                    self.views[view].sort()
                except Exception as e:
                    print(e)
                    print(view)
                    print(self.views[view])
        self.save_views()


    def _add_rows(self, view, list_of_rows, id):
        if not isinstance(list_of_rows, list):
            list_of_rows = [list_of_rows]
        for row in list_of_rows:
            self.views[view].append((row, id))
        # self.views[view].sort() # FIXME do this after all rows have been added from all items 

    def _remove_rows(self, view, id):
        """
        Remove all rows from view corresponding to the given id. This shouldn't affect the sort.
        """
        self.views[view] = [x for x in self.views[view] if x[-1] != id]

    def _update_rows(self, view, list_of_rows, id):
        if list_of_rows:
            self._add_rows(view, list_of_rows, id)

    def _update_created_view(self, item):
        created = timestamp_from_eid(item.eid)
        self._update_rows(
                'created_view',
                [
                    ( item.eid, (), (f"{item['itemtype']} {item['summary']}", created.format(short_dt_fmt)))
                    ],
                item.eid
                )

    def _update_index_view(self, item):
        if 'i' in item:
            tup = item['i'].split(':')
            self._update_rows(
                    'index_view', 
                    [
                        (tup, tup, (f"{item['itemtype']} {item['summary']}"), item.eid)
                        ],
                    item.eid
                    )

    def _update_modified_view(self, item):
        if 'modified' in item:
            modified = item['modified']
            self._update_rows(
                    'modified_view',
                    [
                        ( modified.format(ETMFMT), (), (f"{item['itemtype']} {item['summary']}", modified.format(short_dt_fmt), item.eid)
                        )
                        ],
                item.eid
                    )

    def _update_tags_view(self, item):
        if 't' in item:
            rows = []
            tags = [x.strip() for x in item['t'] if x.strip()]
            if tags:
                for tag in tags:
                    rows.append((tag, tag, (f"{item['itemtype']} {item['summary']}"), item.eid))
                self._update_rows('tags_view', rows, item.eid)

    def _update_done_view(self, item):
        dts = []
        if 'f' in item:
            dts.append(item['f'])
        if 'h' in item:
            dts.extend(item['h'])
        if dts:
            rows = []
            for dt in dts:
                if type(dt) == pendulum.pendulum.Date:
                    dt = pendulum.create(year=dt.year, month=dt.month, day=dt.day, hour=0, minute=0, tz=None)
                rows.append((dt.format(ETMFMT), (fmt_week(dt), dt.format('ddd MMM 2')),  (f"{item['itemtype']} {item['summary']}", dt.format("H:mm"))))
            self._update_rows('done_view', rows, item.eid)

    def _update_relevant(self):
        relevant = None
        hsh = {}
        for ((dt, t, b, f, o), id) in self.views['instances']:
            hsh.setdefault(id, []).append((dt, t, b, f, o))
        for id in hsh:
            status = 'last'
            for (dt, t, b, f, o) in hsh[id]:
                # get the first instance of an unfinished task
                # or the first instance on or after today 
                # or, if none, the last
                today = self.today.format(ETMFMT)
                relevant = dt
                if t == '-':
                    if f:
                        status = 'finished'
                        break
                    elif dt < today:
                        if o:
                            status = 'pastdue'
                            break
                        else:
                            continue
                    else:
                        # not pastdue
                        if b:
                            status = 'begin'
                        else:
                            status = 'available'
                        break
                else:
                    if dt < today:
                        # relevant is the first on or after today
                        continue
                    else:
                        # the first after today
                        if b:
                            status = 'begin'
                        else:
                            status = 'next'
                        break
            self._update_rows('relevant', (relevant, t, status), id)


    def _update_weeks(self, item):
        """
        events and dated unfinished tasks and journal entries 
        sort = (date, type, time)
        path = (year_week, date)
        cols = (display_char summary, ?)
        """
        if (item['itemtype'] in ['?', '!', '~'] 
                or 's' not in item
                ):
            return
        rows = []
        instances = []
        busy = []
        # FIXME deal with jobs: skip finished, add available and waiting
        # only for the next instance
        for (beg, end) in item_instances(item, self.beg_dt, self.end_dt):
            if end is None:
                rhc = ""
            else:
                rhc = fmt_extent(beg, end).center(15, ' ')
            instances.append(beg)
            summary = set_summary(item['summary'], beg)
            sort = (beg.format(ETMFMT))
            path = (fmt_week(beg), beg.format('ddd MMM D'))
            cols = (f"{item['itemtype']} {summary}", rhc)
            rows.append((sort, path, cols))
            if item['itemtype'] == "*" and end:
                beg_min = beg.hour*60 + beg.minute
                end_min = end.hour*60 + end.minute
                tmp = (beg.format("YYYYMMDDT0000"), beg_min, end_min)
                busy.append(tmp)
            self.views['weeks'].setdefault(path[0], []).append((path[1], item.eid))
        self._update_rows('weeks_view', rows, item.eid)
        overdue = 'r' not in item or ('o' in item and item['o'] != 's')
        instance_rows = [(x.format(ETMFMT), item['itemtype'], 'b' in item, 'f' in item, overdue) for x in instances]
        self._update_rows('busy', busy, item.eid)
        self._update_rows('instances', instance_rows, item.eid)


    def _update_agenda(self):
        this_week = fmt_week(self.today)
        this_day = self.today.format("ddd MMM D")
        # this_week_instances = [x for x in self.weeks_view if x[1][0] == this_week]
        # this_day_instances = [x for x in this_week_instances if x[1][1] == this_day]
        this_week_instances = self.views['weeks'].get(this_week, [])
        this_day_instances = [x for x in this_week_instances if x[0] == this_day]
        if not this_day_instances:
            row = (self.today.format(ETMFMT), (this_week, this_day), ("Nothing scheduled", ""))
            self._update_rows('weeks_view', row, "")
            self.modified = True


        # mws = getMonthWeeks(self.today, self.bef_months, self.aft_months)
        # for mw in mws:
        #     key = f"{mw[0]}-{str(mw[1]).zfill(2)}"
        #     if key not in self.views['weeks']:
        #         print("missing week:", key)
        #         self.views['weeks'][key]["0"] = "Nothing scheduled"


    def _update_alerts(self, item):
        if 'a' not in item:
            return
        if 's' not in item:
            return
        alerts = []
        for alert in item['a']:
            cmd = alert[1]
            args = alert[2:]
            for td in alert[0]:
                dt = item['s']-td
                if dt < self.today:
                    continue
                alerts.append(
                        (dt.format(ETMFMT),
                            format_interval(td),
                            f"{item['itemtype']} {item['summary']}",
                            cmd,
                            args,
                            )
                        )
        self._update_rows('alerts', alerts, item.eid)

    def _update_begins(self):
        beg_instances = [x for x in self.views['relevant'] if x[0][2] == 'begin']
        rows = []

        today = self.today.format(ETMFMT)
        for instance in beg_instances:
            id = instance[-1]
            item = self.items.get(eid=id)
            end_begin = beg = instance[0][0]
            beg_dt = parse(beg)
            # the begin interval runs from b days before beg to beg
            start_begin = (beg_dt - pendulum.interval(days=item['b'])).format("YYYYMMDDT0000")
            if start_begin <= today < end_begin:
                days = (beg_dt - self.today).days

                print('begins', start_begin, today, end_begin, days)
                tmp = (today, days)
                self._update_rows('begins', tmp, id)


    def _update_pastdues(self):
        pd_instances = [x for x in self.views['relevant'] if x[0][2] == 'pastdue']
        rows = []

        today = self.today.format(ETMFMT)
        for instance in pd_instances:
            id = instance[-1]
            item = self.items.get(eid=id)
            due = instance[0][0]
            due_dt = parse(due)
            days = (self.today - due_dt).days

            print('pastdue', due, today, days)
            tmp = (today, days)
            self._update_rows('pastdues', tmp, id)




    def _update_all(self):
        for cmd in self.commands:
            print(f'processing {cmd}')
            cmd()


    def process_item(self, item):
        item = item
        self.id = item.eid
        if self.id in self.created:
            # exiting
            self._update_all()
        else:
            # new
            self._update_created()
            self._update_all()


if __name__ == '__main__':
    print('\n\n')
    setup_logging(1)
    import doctest
    my_views = Views()
    print(my_views.beg_dt, my_views.end_dt)

    # for item in my_views.items:
    #     try:
    #         print(item.eid, item['itemtype'])
    #         print(timestamp_from_eid(item.eid))
    #         print(item_details(item))
    #         print()
    #     except Exception as e:
    #         print('\nexception:', e)
    #         pprint(item)



    doctest.testmod()


