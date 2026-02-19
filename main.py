# main.py
import monkey_patch
import gui

# 1. Aplica o Monkey Patch para interceptar as classes do SimPy
monkey_patch.apply_patch()

# 2. Inicia a interface gráfica
if __name__ == "__main__":
    app = gui.SimPyVisualizer()
    app.mainloop()
