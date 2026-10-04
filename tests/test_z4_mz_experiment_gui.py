from copy import deepcopy
import json
from pathlib import Path
import time
from unittest.mock import Mock
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk

import pytest

from auto_annotation_tool.gui import z4_mz_experiment as gui, z4_training_runtime as runtime
from auto_annotation_tool.gui import z4_device_runtime, z4_dataset_sources
from auto_annotation_tool.training.mz_experiment_runtime import MZExperimentSelection
from test_mz_shared_preflight import frozen
from test_z4_async_training_preflight import _Host, _Var, _Widget, _SlowTrainer


class Widget(_Widget):
    def cget(self,name):
        return self.config.get(name,'normal')


class RecordingTrainer(_SlowTrainer):
    def __init__(self):
        super().__init__(delay_s=.005)
        self.requests=[]
        self.is_training=False

    def start_training(self,**kwargs):
        self.requests.append(kwargs)
        return super().start_training(**kwargs)


@pytest.fixture
def host(frozen,monkeypatch):
    protocol,repo,_=frozen
    value=_Host(Path(protocol['dataset']['path']))
    value.trainer=RecordingTrainer()
    value.mz_mode_var=_Var(False)
    value.mz_variant_var=_Var('MZ-n')
    value.mz_status_var=_Var('normal')
    for name,initial in [('epochs_var',17),('batch_var',12),('imgsz_var',640),('lr0_var',.09)]:
        setattr(value,name,_Var(initial))
    for name in ['dataset_variant_var']:
        setattr(value,name,_Var('old variant'))
    for name in ['base_combo','dataset_variant_combo','base_custom_entry','base_custom_btn',
                 'btn_apply_training_recommendation','mz_mode_check','mz_load_button','mz_variant_combo']:
        setattr(value,name,Widget())
    value._train_recommendation_cells=[{'editor':Widget()} for _ in range(4)]
    value.base_combo.configure(state='readonly')
    value.dataset_variant_combo.configure(state='readonly')
    value.base_custom_entry.configure(state='disabled')
    value.base_custom_btn.configure(state='disabled')
    value._get_custom_base_model_label=lambda:'Custom'
    value._is_custom_base_model_key=lambda key:key=='Custom'
    value._safe_training_int_value=lambda name,default=0,minimum=0:max(int(getattr(value,name).get()),minimum)
    value._safe_training_float_value=lambda name,default=0.01,minimum=0.0:max(float(getattr(value,name).get()),minimum)
    monkeypatch.setattr(runtime,'YOLO_AVAILABLE',True)
    monkeypatch.setattr(runtime,'cleanup_gpu_memory',Mock())
    monkeypatch.setattr(gui.CAMPAIGN,'get_active_project_name',lambda:'')
    value.errors=Mock()
    monkeypatch.setattr(gui.messagebox,'showerror',value.errors)
    def prepare(candidate,variant):
        # Deliberately slow, to prove the shared validation stays off Tk's thread.
        time.sleep(.025)
        return MZExperimentSelection(deepcopy(candidate),variant,{'ok':True})
    monkeypatch.setattr(gui,'prepare_mz_experiment',prepare)
    yield value,protocol,repo
    value.frame.destroy()


def pump(host):
    deadline=time.perf_counter()+4
    while (getattr(host,'_mz_validation_in_progress',False) or getattr(host,'_training_start_in_progress',False)) and time.perf_counter()<deadline:
        host.frame.pump()
        time.sleep(.005)
    host.frame.pump()
    assert not getattr(host,'_mz_validation_in_progress',False)
    assert not getattr(host,'_training_start_in_progress',False)


def activate(host,protocol,repo,variant='MZ-n'):
    path=repo/'protocol.json';path.write_text(json.dumps(protocol),encoding='utf-8')
    host.mz_variant_var.set(variant)
    gui.load_protocol(host,path)
    pump(host)
    assert gui.is_active(host)


@pytest.mark.parametrize('variant',['MZ-n','MZ-s'])
def test_gui_dispatches_exact_frozen_request_through_existing_start_path(host,variant):
    value,protocol,repo=host
    activate(value,protocol,repo,variant)
    effective_profile=Mock(return_value=('cuda:0',None))
    value._get_effective_training_device_profile=effective_profile
    # Even a programmatic change to the displayed values cannot replace the
    # protocol's input. Disabled controls alone are not the execution contract.
    value.epochs_var.set(2);value.batch_var.set(99);value.device_var.set('cpu')
    value.name_var.set('edited');value.dataset_var.set('edited')
    runtime._start_training(value)
    runtime._start_training(value)
    pump(value)
    assert value.trainer.calls==1
    effective_profile.assert_called_once_with('cuda:0')
    request=value.trainer.requests[0]
    expected={'name':'E-MZ-NS-01_'+variant,'dataset_path':protocol['dataset']['path'],
        'base_model':protocol['models'][variant]['checkpoint'],'epochs':100,'batch_size':4,
        'img_size':320,'device':0,'lr0':.01,'training_target':'char','strict_experiment':True,
        'experiment_id':'E-MZ-NS-01','training_protocol':protocol['training'],'validate_custom_model':False}
    assert {key:val for key,val in request.items() if key!='progress_callback'}==expected
    assert request['training_protocol']['seed']==42 and request['training_protocol']['optimizer']=='SGD'
    assert request['training_protocol']['amp'] is False
    assert not {'resume_from','parent_run_id','lineage_mode'} & request.keys()
    assert 'Tryb: eksperyment kontrolowany • STRICT' in value._logs
    assert 'Protokół zweryfikowany' in value.mz_status_var.get()


def test_activation_locks_fields_and_deactivation_restores_normal_values_and_states(host):
    value,protocol,repo=host
    before={name:getattr(value,name).get() for name in gui._FIELDS}
    states=[widget.cget('state') for widget in gui._frozen_widgets(value)]
    activate(value,protocol,repo)
    assert value.epochs_var.get()==100 and value.batch_var.get()==4
    assert value.base_custom_var.get().endswith('yolo26n.pt')
    assert all(widget.cget('state')=='disabled' for widget in gui._frozen_widgets(value))
    gui.disable_mode(value)
    assert not gui.is_active(value)
    assert before=={name:getattr(value,name).get() for name in gui._FIELDS}
    assert states==[widget.cget('state') for widget in gui._frozen_widgets(value)]


def test_variants_switch_verified_model_and_keep_recipe(host):
    value,protocol,repo=host
    activate(value,protocol,repo)
    first=(value.epochs_var.get(),value.batch_var.get(),value.imgsz_var.get(),value.lr0_var.get())
    value.mz_variant_var.set('MZ-s')
    gui.select_variant(value);pump(value)
    assert value.base_custom_var.get().endswith('yolo26s.pt')
    assert first==(value.epochs_var.get(),value.batch_var.get(),value.imgsz_var.get(),value.lr0_var.get())
    assert value.name_var.get()=='E-MZ-NS-01_MZ-s'


def test_failed_load_never_activates_or_changes_training_fields(host,monkeypatch):
    value,protocol,repo=host
    before={name:getattr(value,name).get() for name in gui._FIELDS}
    def fail(*args): raise ValueError('changed assignment')
    monkeypatch.setattr(gui,'prepare_mz_experiment',fail)
    path=repo/'bad.json';path.write_text(json.dumps(protocol))
    gui.load_protocol(value,path);pump(value)
    assert not gui.is_active(value)
    assert before=={name:getattr(value,name).get() for name in gui._FIELDS}
    assert value.trainer.calls==0 and value.errors.called


def test_start_revalidates_before_exclusive_operation_and_never_creates_run_if_changed(host,monkeypatch):
    value,protocol,repo=host
    activate(value,protocol,repo)
    begin=Mock(return_value=True);value._begin_step4_operation=begin
    def fail(*args): raise ValueError('split changed')
    monkeypatch.setattr(gui,'prepare_mz_experiment',fail)
    runtime._start_training(value);pump(value)
    begin.assert_not_called()
    assert value.trainer.calls==0


def test_active_fine_tune_context_blocks_controlled_start(host):
    value,protocol,repo=host
    activate(value,protocol,repo)
    value._step4_fine_tune_parent_run_id='human-selected-parent'
    runtime._start_training(value)
    assert value.trainer.calls==0 and value.errors.called
    assert value._step4_fine_tune_parent_run_id=='human-selected-parent'


@pytest.mark.parametrize('action',[runtime._resume_selected_run,runtime._select_selected_run_as_fine_tune_base,
                                  runtime._select_selected_ranking_run_as_fine_tune_base])
def test_resume_and_fine_tune_actions_are_blocked_before_history_access(host,action):
    value,protocol,repo=host
    activate(value,protocol,repo)
    value._selected_run=Mock(side_effect=AssertionError('history must not be accessed'))
    action(value)
    value._selected_run.assert_not_called()
    assert value.trainer.calls==0 and value.errors.called


def test_normal_gui_keeps_editable_values_and_has_no_strict_flags(host):
    value,protocol,repo=host
    runtime._start_training(value);pump(value)
    request=value.trainer.requests[0]
    assert request['epochs']==17 and request['batch_size']==12 and request['img_size']==640
    assert request['lr0']==.09 and request['device']=='cpu' and request['base_model']=='yolo11n'
    assert 'strict_experiment' not in request and 'training_protocol' not in request


def test_background_refresh_cannot_reenable_dataset_or_override_frozen_device(host):
    value,protocol,repo=host
    activate(value,protocol,repo)
    value._get_global_training_device_choice=lambda:'cpu'
    z4_device_runtime._refresh_training_device_hint(value)
    z4_dataset_sources._refresh_dataset_variant_choices(value)
    assert str(value.device_var.get())=='0'
    assert value.dataset_variant_combo.cget('state')=='disabled'


def test_section_builds_real_tk_controls_without_constructing_trainer():
    root=tk.Tk()
    root.withdraw()
    try:
        frame=ttk.Frame(root)
        value=SimpleNamespace(frame=frame,_register_train_left_wrap_target=lambda *args,**kwargs:None)
        section=gui.build_section(value,frame)
        root.update_idletasks()
        assert section.cget('text').strip()=='Eksperyment kontrolowany'
        assert value.mz_mode_check.cget('text')=='Tryb kontrolowany'
        assert value.mz_load_button.cget('text')=='Wczytaj protokół eksperymentu'
        assert tuple(value.mz_variant_combo.cget('values'))==('MZ-n','MZ-s')
        assert not value.mz_mode_var.get()
        assert section.winfo_reqheight()<180
    finally:
        root.destroy()
