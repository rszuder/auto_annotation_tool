"""One analysis window with per-metric evidence and explicit unavailable rows."""
from pathlib import Path
import json,queue,threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .mobile_analysis import analyze,QUESTIONS,METRICS,PROTOCOL_ID
from .mobile_analysis_export import make_figure,export_analysis

class UnifiedAnalysisWindow(tk.Toplevel):
    def __init__(self,parent,cohort,results_root=None):
        super().__init__(parent)
        self.title('ALPR — analiza wybranych raportów');self.geometry('1210x780');self.minsize(980,650)
        self.cohort=cohort;self.root_path=Path(results_root) if results_root else None
        self.drawn=None;self.figure=None;self._closed=False;self._busy=False;self._queue=queue.SimpleQueue()
        self._pending=None;self.last_export=None
        self._build();self._set_cohort(cohort);self._poll()
        self.protocol('WM_DELETE_WINDOW',self._close)

    def _build(self):
        shell=ttk.Frame(self,padding=10);shell.pack(fill='both',expand=True)
        shell.columnconfigure(0,weight=0,minsize=310);shell.columnconfigure(1,weight=1);shell.rowconfigure(2,weight=1)
        self.protocol_label=ttk.Label(shell,text=PROTOCOL_ID+' · retrospektywnie dla F4 · DESCRIPTIVE',font=('Segoe UI',10,'bold'))
        self.protocol_label.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,6))
        controls=ttk.Frame(shell);controls.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(0,8))
        controls.columnconfigure(1,weight=1);controls.columnconfigure(3,weight=1)
        ttk.Label(controls,text='Pytanie').grid(row=0,column=0,padx=(0,5))
        self.question=ttk.Combobox(controls,state='readonly',values=list(QUESTIONS.values()),width=26)
        self.question.grid(row=0,column=1,sticky='ew',padx=(0,12));self.question.set(QUESTIONS[self.cohort.question])
        self.question.bind('<<ComboboxSelected>>',self._change_question)
        ttk.Label(controls,text='Miara').grid(row=0,column=2,padx=(0,5))
        self.metric=ttk.Combobox(controls,state='readonly',values=[v[0] for v in METRICS.values()],width=38)
        self.metric.grid(row=0,column=3,sticky='ew');self.metric.current(0);self.metric.bind('<<ComboboxSelected>>',lambda e:self._render())
        left=ttk.Frame(shell);left.grid(row=2,column=0,sticky='nsew',padx=(0,10));left.columnconfigure(0,weight=1);left.rowconfigure(3,weight=1)
        ttk.Label(left,text='Wybrane źródła · dostępność tej miary',font=('Segoe UI',9,'bold')).grid(row=0,column=0,sticky='w')
        self.sources=ttk.Treeview(left,columns=('session','status','n'),show='headings',height=7,selectmode='browse')
        for key,label,width in (('session','Sesja',125),('status','Miara',105),('n','n / braki',80)):
            self.sources.heading(key,text=label);self.sources.column(key,width=width,minwidth=width,stretch=False)
        self.sources.grid(row=1,column=0,sticky='ew',pady=(5,7));self.sources.bind('<<TreeviewSelect>>',lambda e:self._details())
        ttk.Button(left,text='Usuń wybraną sesję',command=self._remove_selected).grid(row=2,column=0,sticky='ew',pady=(0,7))
        self.details=tk.Text(left,width=38,height=14,wrap='word',font=('Segoe UI',9),state='disabled',relief='flat')
        self.details.grid(row=3,column=0,sticky='nsew')
        actions=ttk.Frame(left);actions.grid(row=4,column=0,sticky='ew',pady=(8,0));actions.columnconfigure(0,weight=1)
        self.refresh_button=ttk.Button(actions,text='Odśwież źródła i ocenę',command=self.refresh);self.refresh_button.grid(row=0,column=0,sticky='ew')
        self.save_button=ttk.Button(actions,text='Zapisz PNG + SVG + CSV + JSON',command=self.save);self.save_button.grid(row=1,column=0,sticky='ew',pady=(5,0))
        right=ttk.Frame(shell);right.grid(row=2,column=1,sticky='nsew');right.columnconfigure(0,weight=1);right.rowconfigure(2,weight=1)
        self.explanation=ttk.Label(right,text='Porównanie opisowe. Różne podzbiory jakości nie uzasadniają rankingu wariantów.',wraplength=900)
        self.explanation.grid(row=0,column=0,sticky='ew',pady=(0,7))
        self.scenario=ttk.Combobox(right,state='readonly');self.scenario.grid(row=1,column=0,sticky='ew',pady=(0,5))
        self.scenario.bind('<<ComboboxSelected>>',lambda e:self._render())
        self.chart=ttk.Frame(right);self.chart.grid(row=2,column=0,sticky='nsew')
        self.status=tk.StringVar(value='Źródła mają osobne n i przyczyny braków. Brak danych nie jest zerem.')
        self.status_label=ttk.Label(shell,textvariable=self.status,wraplength=1150,justify='left')
        self.status_label.grid(row=3,column=0,columnspan=2,sticky='ew',pady=(8,0))
        self.bind('<Configure>',self._resize,add='+')

    def _resize(self,event):
        if event.widget is self:
            self.explanation.configure(wraplength=max(350,event.width-350));self.status_label.configure(wraplength=max(700,event.width-25))

    def metric_id(self):return list(METRICS)[max(0,self.metric.current())]

    def _set_cohort(self,cohort):
        previous=self.scenario.get();self.cohort=cohort
        values=sorted({s.metadata.get('scenario','NIEOKREŚLONY') for s in cohort.sessions})
        self.scenario.configure(values=values);self.scenario.set(previous if previous in values else values[0] if values else '')
        self._render()

    def _clear_figure(self):
        import matplotlib.pyplot as plt
        if self.drawn is not None:self.drawn.get_tk_widget().destroy();self.drawn=None
        if self.figure is not None:plt.close(self.figure);self.figure=None

    def _render(self):
        self._clear_figure();previous=self.sources.selection();self.sources.delete(*self.sources.get_children())
        key=self.metric_id()
        for i,s in enumerate(self.cohort.sessions):
            m=s.metrics[key];n='N/A' if m.n_scored is None else str(m.n_scored);missing='N/A' if m.n_unscored is None else str(m.n_unscored)
            self.sources.insert('',tk.END,iid=str(i),values=(f"{s.metadata.get('variant')} {s.metadata.get('repeat')}",m.status,f'{n} / {missing}'))
        if self.cohort.sessions:
            selected=previous[0] if previous and self.sources.exists(previous[0]) else '0'
            self.sources.selection_set(selected);self._details()
        if not self.scenario.get():return
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self.figure=make_figure(self.cohort,key,self.scenario.get());self.drawn=FigureCanvasTkAgg(self.figure,master=self.chart)
        self.drawn.get_tk_widget().pack(fill='both',expand=True)
        self.drawn.get_tk_widget().bind('<Configure>',self._fit,add='+');self.drawn.get_tk_widget().bind('<Map>',lambda e:self.after_idle(self._fit),add='+')
        self._fit();self.drawn.draw()

    def _fit(self,event=None):
        from .mobile_import_comparison_gui import ImportedMobileComparisonWindow
        ImportedMobileComparisonWindow._fit_preview_text(self,event)

    def _details(self):
        selected=self.sources.selection()
        if not selected:return
        s=self.cohort.sessions[int(selected[0])];m=s.metrics[self.metric_id()]
        value='N/A' if m.value is None else f'{m.value:.4f} {METRICS[m.metric_id][1]}'
        shown=lambda v:'N/A' if v is None else str(v)
        lines=['Miara: '+m.status+' · '+value,
            f'n={shown(m.n_scored)}, ogółem={shown(m.n_total_eligible)}, braki={shown(m.n_unscored)}',
            f'Licznik/mianownik: {shown(m.numerator)}/{shown(m.denominator)}',m.explanation,
            'Powody: '+(', '.join(m.missing_reasons) or 'brak')]
        if s.quality_units:
            names={'FINAL_SOURCE_BBOX_UNAVAILABLE':'brak wiarygodnego BBOX modelu',
                'GT_GEOMETRY_UNCONFIRMED':'brak potwierdzonego obrysu referencyjnego','MT_NOT_COMPLETED':'MT nie zakończyło pracy'}
            missing=[u for u in s.quality_units if u['status']!='MEASURED']
            if missing:lines+=['','Nieocenialne jednostki BBOX:']+[u['label']+': '+', '.join(names.get(r,r) for r in u['missing_reasons']) for u in missing]
        lines+=['','GT: '+m.gt_origin+' · rewizja: '+shown(m.review_revision),'Jednostka: '+METRICS[m.metric_id][2],
            'Ocena operatora: '+s.quality_state,'Źródło: '+s.source_status,s.input.session_id,s.input.report_id,'SHA: '+s.input.source_sha256,
            '','Kontrola warunków (nie jest zatwierdzeniem przyczynowości):']
        for row in s.conditions.get('rows',[]):lines.append(f'{row[0]}: {row[1]} / {row[2]} — {row[3]}. {row[4]}')
        self.details.configure(state='normal');self.details.delete('1.0',tk.END);self.details.insert('1.0','\n'.join(lines));self.details.configure(state='disabled')

    def _work(self,fn,on_done):
        if self._busy:return
        self._busy=True;self.save_button.configure(state='disabled');self.refresh_button.configure(state='disabled')
        self.question.configure(state='disabled');self.status.set('Sprawdzam źródła i wersje ocen…')
        self.metric.configure(state='disabled');self.scenario.configure(state='disabled')
        def worker():
            try:self._queue.put((on_done,fn(),None))
            except Exception as exc:self._queue.put((on_done,None,str(exc)))
        threading.Thread(target=worker,daemon=True,name='alpr-analysis-read-export').start()

    def _poll(self):
        if self._closed:return
        try:
            while True:
                done,value,error=self._queue.get_nowait();self._busy=False
                self.save_button.configure(state='normal');self.refresh_button.configure(state='normal');self.question.configure(state='readonly')
                self.metric.configure(state='readonly');self.scenario.configure(state='readonly')
                if error:self.status.set('Nie wykonano operacji: '+error)
                else:done(value)
        except queue.Empty:pass
        self._pending=self.after(60,self._poll)

    def _change_question(self,event=None):
        question=next(k for k,v in QUESTIONS.items() if v==self.question.get())
        self._work(lambda:analyze(self.cohort.inputs,question),lambda c:(self._set_cohort(c),self.status.set('Zakres pytania sprawdzony. Brak źródła dla F5/F6 nie tworzy wyniku.')))

    def refresh(self):
        self._work(lambda:analyze(self.cohort.inputs,self.cohort.question),lambda c:(self._set_cohort(c),self.status.set('Źródła i bieżące oceny sprawdzone. Stary eksport GT nie zasila jakości.')))

    def _remove_selected(self):
        if self._busy:return
        selected=self.sources.selection()
        if not selected:return
        removed=int(selected[0]);inputs=[i for j,i in enumerate(self.cohort.inputs) if j!=removed]
        self._work(lambda:analyze(inputs,self.cohort.question),self._set_cohort)

    def save(self):
        if self._busy or not self.cohort.sessions:return
        if self.root_path is None:
            name=filedialog.askdirectory(parent=self,title='Wskaż istniejący katalog 03_wyniki')
            if not name:return
            self.root_path=Path(name)
        def done(result):
            path,cohort=result;self.last_export=path;self._set_cohort(cohort);self.status.set('Zapisano zweryfikowaną analizę: '+str(path))
        self._work(lambda:export_analysis(self.cohort,self.root_path),done)

    def _close(self):
        self._closed=True
        if self._pending:self.after_cancel(self._pending)
        self._clear_figure();self.destroy()
