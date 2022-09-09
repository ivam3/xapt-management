import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter.font import Font
from tkinter.messagebox import showinfo
import sys, os, subprocess
import threading

font_global = ("Garamond Italic", 5, "bold") 


class Redirect():
    
    def __init__(self, widget, autoscroll=True):
        self.widget = widget
        self.autoscroll = autoscroll

    def write(self, text):
        self.widget.insert('end', text)
        if self.autoscroll:
            self.widget.see("end")  # autoscroll

    #def flush(self):
    #    pass


def run(cmd):
    threading.Thread(target=xapt(cmd)).start()


def xapt(cmd):
    if cmd == "list":
        return os.popen("apt list|awk -F '/' '{print $1}'|sort -r").read()
    else:
        if cmd == "upgrade":
            os.system('apt update')
            command = "apt upgrade -y"
        if cmd == "show":
            pkg = dropkg.get()
            command = "apt show " + pkg
        else:
            pkg = dropkg.get()
            command = "apt " + cmd + " " + pkg + " -y"

        print(command)
        p = subprocess.Popen("".join(command).split(), stdout=subprocess.PIPE, bufsize=1, text=True)
        while p.poll() is None:
            msg = p.stdout.readline().strip() # read a line from the process output
            if msg:
                print(msg)

        print("DONE!!")


def about_popup():
    popup = tk.Toplevel()
    popup.wm_title("About x11 Advance Package Tool(APT) Management")
    popup.geometry("600x250")
    popup.maxsize(600,250)
    popup.configure(background="mint cream", relief='solid', borderwidth=5)
    tk.Label(
            popup,
            font="Helvetica 8",
            justify='left',
            bg='mint cream',
            relief='flat',
            text="Xapt Management: is a graphical interface\nfor Advance Package Tool(APT) written in python\n\nVersion: 1.0\nMaintainer: @Ivam3\nContainer: https://github.com/ivam3/xapt-management\nFeedback: https://t.me/Ivam3_Bot"
            ).pack(fill='both',expand=True)

    b = ttk.Button(popup, text="Okay", command=popup.destroy) 
    b.pack(padx=10,pady=20)


    
# create the application
root = tk.Tk()
app_path=sys.path[0]
root.iconphoto(True, tk.PhotoImage(file=os.path.join(app_path, "./img/xapt.png")))
root.title("x11 Advance Package Tool(APT) Management")
root.geometry("830x500")
root.maxsize(830, 500)
root.configure(background="mint cream", relief='solid', borderwidth=5)

# VARIABLES
dropkg = tk.StringVar(root)

# BARRA DE MENU
header = tk.Frame(root, relief='solid', bg="mint cream", borderwidth=1)
header.pack(
        fill="x", ##HORIZONTAL
        expand=False
        )

menu = tk.Button(
            header,
            text="About",
            font=('Calibri', 10),
            justify="left",
            padx=0,pady=0,
            anchor='nw',
            cursor='hand2',
            relief='flat',
            bg="azure",
            fg="slate gray",
            activebackground='mint cream',
            command=lambda:about_popup()
            )
menu.pack(
        side="left",
        )


# DROPBOX DE PKGS  ::: tk.OptionMenu || ttk.Combobox
droppkglist = ttk.Combobox(root, values=xapt("list"), textvariable=dropkg, width=20, font=('Geramond 10'))
droppkglist.pack(
        side="left",
        fill="x",
        expand=True
        )
droppkglist.place(x=10,y=55)

picdownload = tk.PhotoImage(file='./img/download.png')
binstall = tk.Button(
        root,
        text="install",
        padx=5, pady=6,
        image=picdownload,
        command=lambda: run("install"),
        justify='left',
        cursor='hand2',
        font=font_global,
        compound='left',
        relief="groove", overrelief="sunken", borderwidth=3,
        bg='ghost white', fg='black', activebackground='ghost white'
        )
binstall.pack(
        side="top",
        )
binstall.place(x=350,y=50)

picrm = tk.PhotoImage(file='./img/uninstall.png')
brm = tk.Button(
        root,
        text="uninstall",
        padx=5, pady=5,
        cursor='hand2',
        image=picrm,
        compound='left',
        font=font_global,
        command=lambda: run("remove"),
        relief="groove", overrelief="sunken", borderwidth=3,
        bg='ghost white', fg='black', activebackground='ghost white'
        )
brm.pack(
        side="top",
        )
brm.place(x=445,y=50)

picinfo = tk.PhotoImage(file='./img/info.png')
binfo = tk.Button(
        root,
        text="info",
        justify='left',
        cursor='hand2',
        padx=5, pady=5,
        font=font_global,
        image=picinfo,
        compound='left',
        command=lambda: run("show"),
        relief="groove", overrelief="sunken", borderwidth=3,
        bg='ghost white', fg='black', activebackground='ghost white'
        )
binfo.pack(
        side="top",
        )
binfo.place(x=555,y=50)

picfix = tk.PhotoImage(file='./img/fix.png')
bfix = tk.Button(
        root,
        text="upgrade",
        padx=5, pady=5,
        cursor='hand2',
        image=picfix,
        compound='left',
        font=font_global,
        command=lambda: run("upgrade"),
        relief="groove", overrelief="sunken", borderwidth=3,
        bg='ghost white', fg='black', activebackground='ghost white'#, activeforeground='black'
        )
bfix.pack(
        side="top",
        )
bfix.place(x=636,y=50)
#print(bfix.winfo_class())  #Imprime el nombre de la llamada del widget

picsch = tk.PhotoImage(file='./img/searching.png')
bsch = tk.Button(
        root,
        text="Search",
        cursor='hand2',
        padx=5, pady=8,
        font=font_global,
        image=picsch,
        compound='left',
        command=lambda: run("search"),
        relief="groove", overrelief="sunken", borderwidth=3,
        bg='ghost white', fg='black', activebackground='ghost white'
        )
bsch.pack(
        side="top"
        )
bsch.place(x=730,y=50)


frame = tk.Frame(root)
frame.pack(expand=True, fill='both')
frame.place(x=10,y=115)

terminal = tk.Text(
    root,
    font=("Garamond 10"),
    width=60,
    height=14,
    relief='sunken',
    borderwidth=10,
    bg="bisque",
    fg="black"
    )
terminal.pack(
        expand=True
        )
terminal.place(x=10,y=100)

scrollbar = tk.Scrollbar(frame)
scrollbar.pack(side='right', fill='y')

terminal['yscrollcommand'] = scrollbar.set
scrollbar['command'] = terminal.yview

# refresh preocess in window 
old_stdout = sys.stdout    
sys.stdout = Redirect(terminal)

# start the program
root.mainloop()

sys.stdout = old_stdout
