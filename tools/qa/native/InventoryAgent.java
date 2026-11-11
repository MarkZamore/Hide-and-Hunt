import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.ProtectionDomain;
import java.util.Collection;
import java.util.Objects;
import java.util.TreeMap;

import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** QA-only observer for the real Fabric registry. Never packaged as a mod. */
public final class InventoryAgent {
    private InventoryAgent() {}

    public static void premain(String output, Instrumentation instrumentation) {
        instrumentation.addTransformer(new ClassFileTransformer() {
            @Override
            public byte[] transform(ClassLoader loader, String name, Class<?> type,
                                    ProtectionDomain domain, byte[] bytes) {
                if (!"link/e4steam/steam/SteamworksApi".equals(name)) return null;
                // The genuine e4steam JAR still goes through Fabric/Mixin. Refuse
                // actual Steam native authentication even if a client is open.
                ClassReader reader = new ClassReader(bytes);
                ClassWriter writer = new ClassWriter(reader, 0);
                int[] found = {0};
                reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
                    @Override
                    public MethodVisitor visitMethod(int access, String method, String descriptor,
                                                     String signature, String[] exceptions) {
                        MethodVisitor visitor = super.visitMethod(access, method, descriptor, signature, exceptions);
                        if (!method.equals("init") || !descriptor.equals("()Z")) return visitor;
                        found[0]++;
                        visitor.visitCode();
                        visitor.visitInsn(Opcodes.ICONST_0);
                        visitor.visitInsn(Opcodes.IRETURN);
                        visitor.visitMaxs(1, (access & Opcodes.ACC_STATIC) == 0 ? 1 : 0);
                        visitor.visitEnd();
                        return null;
                    }
                }, 0);
                if (found[0] != 1) throw new AssertionError("Unexpected e4steam SteamworksApi.init");
                System.out.println("QA_STEAM_NATIVE_INIT_REFUSED");
                return writer.toByteArray();
            }
        });
        Thread thread = new Thread(() -> capture(instrumentation, Path.of(output)), "fabric-qa-inventory");
        thread.setDaemon(true);
        thread.start();
    }

    private static void capture(Instrumentation instrumentation, Path output) {
        try {
            Class<?> fabric = null;
            boolean gameLoaded = false;
            for (int attempt = 0; attempt < 600 && !gameLoaded; attempt++) {
                for (Class<?> loaded : instrumentation.getAllLoadedClasses()) {
                    if (loaded.getName().equals("net.fabricmc.loader.api.FabricLoader")) fabric = loaded;
                    if (loaded.getName().equals("net.minecraft.client.Minecraft")) gameLoaded = true;
                }
                if (!gameLoaded) Thread.sleep(250);
            }
            if (!gameLoaded) throw new IllegalStateException("The client class was not loaded");
            ClassLoader loader = Objects.requireNonNull(fabric).getClassLoader();
            Class<?> container = Class.forName("net.fabricmc.loader.api.ModContainer", false, loader);
            Class<?> metadata = Class.forName("net.fabricmc.loader.api.metadata.ModMetadata", false, loader);
            Class<?> version = Class.forName("net.fabricmc.loader.api.Version", false, loader);
            Class<?> origin = Class.forName("net.fabricmc.loader.api.metadata.ModOrigin", false, loader);
            Object runtime = fabric.getMethod("getInstance").invoke(null);
            var versions = new TreeMap<String, String>();
            var origins = new TreeMap<String, String>();
            for (Object mod : (Collection<?>) fabric.getMethod("getAllMods").invoke(runtime)) {
                Object data = container.getMethod("getMetadata").invoke(mod);
                String id = (String) metadata.getMethod("getId").invoke(data);
                Object resolved = metadata.getMethod("getVersion").invoke(data);
                versions.put(id, (String) version.getMethod("getFriendlyString").invoke(resolved));
                Object source = container.getMethod("getOrigin").invoke(mod);
                String kind = origin.getMethod("getKind").invoke(source).toString();
                String provenance = switch (kind) {
                    case "PATH" -> origin.getMethod("getPaths").invoke(source).toString();
                    case "NESTED" -> origin.getMethod("getParentModId").invoke(source) + "!"
                                     + origin.getMethod("getParentSubLocation").invoke(source);
                    default -> kind;
                };
                origins.put(id, provenance);
            }
            if (!versions.containsKey("hideandhunt") || !versions.containsKey("minecraft"))
                throw new IllegalStateException("Fabric's registry is incomplete");
            write(output, versions);
            write(output.resolveSibling("mod-origins.json"), origins);
            System.out.println("QA_NATIVE_FABRIC_INVENTORY count=" + versions.size());
        } catch (Exception failure) {
            System.err.println("QA_NATIVE_FABRIC_INVENTORY_FAILED");
            failure.printStackTrace();
        }
    }

    private static void write(Path output, TreeMap<String, String> data) throws Exception {
        var json = new StringBuilder("{\n");
        for (var row : data.entrySet())
            json.append("  ").append(quoted(row.getKey())).append(": ").append(quoted(row.getValue())).append(",\n");
        json.setLength(json.length() - 2);
        Files.writeString(output, json.append("\n}\n"), StandardCharsets.UTF_8);
    }

    private static String quoted(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"")
            .replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t") + "\"";
    }
}
