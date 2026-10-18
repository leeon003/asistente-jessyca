using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class JessycaLauncher
{
    [STAThread]
    private static void Main()
    {
        try
        {
            string root = @"D:\JESSYCA 3.0\asistente-jessyca";
            string python = Path.Combine(root, @"venv\Scripts\pythonw.exe");
            string entry = Path.Combine(root, "jessyca_escritorio.pyw");
            if (!File.Exists(python) || !File.Exists(entry))
                throw new FileNotFoundException("No se encontró la instalación de Jessyca en " + root);
            Process.Start(new ProcessStartInfo {
                FileName = python, Arguments = "\"" + entry + "\"", WorkingDirectory = root,
                UseShellExecute = false, CreateNoWindow = true
            });
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "JESSYCA", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
