"""Keep avar metadata in native documents; FontLab's Save remains untouched.

One process-wide listener, no timer, no retained font/package wrappers. Only
fonts explicitly used in the hybrid or already carrying its record are watched.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from . import axis_map


def embed(source):
    """Update only our lib key, immediately before the host serializes it."""
    import fontpr
    axes = axis_map.effective_axes(source.package)
    blob = axis_map.embedded_value(source.package)
    if blob is None:
        info = axis_map.with_native_axes(fontpr.get_font_info(font_id=source.package.fgId), axes)
        reference = axis_map.capture(source.font.path,info,axes)
        if reference['status'] != 'ready':
            return {'status':'unavailable','reason':reference.get('reason','Нет исходной avar')}
        axis_map.verify_reference(reference,axes)
        allowed = True
    else:
        old = axis_map.decode_embedded(blob)
        reference = old['reference']
        allowed = old['restore_allowed'] and axis_map.canonical(axes)==axis_map.canonical(reference['axes_snapshot'])
    value = axis_map.encode_embedded(reference,axes,allowed)
    changed = value != blob
    if changed:
        values = dict(source.package.packageLib)
        values[axis_map.LIB_KEY] = value
        source.package.packageLib = values
    return {'status':'embedded' if allowed else 'authored','changed':changed,
            'avar_sha256':reference['avar_sha256']}


class Service:
    SIGNALS = [('packageReaded(flPackage)','opened'),('packageAdded(flPackage)','opened'),
               ('signalPackageClosed(flPackage)','closed'),('packageRemoved(flPackage)','closed'),
               ('packageUpdated(flPackage)','updated'),('signalPackageUpdated(uint,bool)','changed'),
               ('signalPackageContentUpdated(uint,uint)','changed'),('signalSaveProgress(bool)','saving')]

    def __init__(self, identifiers=()):
        import fontlab as fl
        self.identifiers=set(identifiers);self.errors={};self.busy=False;self.connections=[]
        self.items=fl.flItems.instance().qobject
        try:
            for signal,method in self.SIGNALS:
                callback=getattr(self,method)
                if self.items.connect(signal,callback) is False:
                    raise RuntimeError('FontLab не подключил событие '+signal)
                self.connections.append((signal,callback))
        except Exception:
            self.stop();raise

    def stop(self):
        for signal,callback in self.connections:self.items.disconnect(signal,callback)
        self.connections.clear()

    def watch(self,source):
        identifier=source.package.fgId
        self.identifiers.add(identifier)
        self.busy=True
        try:
            result=embed(source)
            if result['status']=='unavailable':self.identifiers.discard(identifier)
            return result
        finally:self.busy=False

    def sync(self):
        if self.busy:return
        import fontlab as fl
        self.busy=True
        try:
            live=set()
            for font in fl.AllFonts():
                package=fl.flPackage(font);identifier=package.fgId;live.add(identifier)
                if identifier not in self.identifiers:continue
                try:
                    embed(SimpleNamespace(font=font,package=package))
                    self.errors.pop(identifier,None)
                except Exception as error:self.errors[identifier]=str(error)
            self.identifiers.intersection_update(live)
            self.errors={i:e for i,e in self.errors.items() if i in live}
        finally:self.busy=False

    def opened(self,package):
        if Path(str(package.fileName)).stem.startswith('autokerner9-'):
            self.identifiers.discard(package.fgId)
            return
        if axis_map.LIB_KEY in package.packageLib:self.identifiers.add(package.fgId)

    def closed(self,package):
        self.identifiers.discard(package.fgId);self.errors.pop(package.fgId,None)

    def updated(self,package):
        if package.fgId in self.identifiers:self.sync()

    def changed(self,*args):self.sync()

    def saving(self,active):
        if active:self.sync()


def install():
    previous=getattr(sys,'_autokerner9_avar_service',None)
    identifiers=tuple(previous.identifiers) if previous is not None else ()
    if previous is not None:previous.stop()
    service=Service(identifiers)
    sys._autokerner9_avar_service=service
    return service


def watch(source):
    service=getattr(sys,'_autokerner9_avar_service',None)
    if not isinstance(service,Service) or not service.connections:service=install()
    return service.watch(source)
